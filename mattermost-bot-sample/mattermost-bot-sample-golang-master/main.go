package main

import (
	"context"
	"crypto/tls"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"os/signal"
	"regexp"
	"time"

	"github.com/gorilla/websocket"
	"github.com/mattermost/mattermost/server/public/model"
	"github.com/rs/zerolog"
)

func main() {

	app := &application{
		logger: zerolog.New(
			zerolog.ConsoleWriter{
				Out:        os.Stdout,
				TimeFormat: time.RFC822,
			},
		).With().Timestamp().Logger(),
	}

	app.config = loadConfig()
	app.logger.Info().Str("config", fmt.Sprint(app.config)).Msg("")

	setupGracefulShutdown(app)

	// Create a new mattermost client.
	app.mattermostClient = model.NewAPIv4Client(app.config.mattermostServer.String())

	if app.config.SkipVerify {
		app.mattermostClient.HTTPClient.Transport = &http.Transport{
			TLSClientConfig: &tls.Config{InsecureSkipVerify: true},
		}
	}

	// Login.
	app.mattermostClient.SetToken(app.config.mattermostToken)

	if user, resp, err := app.mattermostClient.GetUser(context.Background(), "me", ""); err != nil {
		app.logger.Fatal().Err(err).Msg("Could not log in")
	} else {
		app.logger.Debug().Interface("user", user).Interface("resp", resp).Msg("")
		app.logger.Info().Msg("Logged in to mattermost")
		app.mattermostUser = user
	}

	clientConfig, _, err := app.mattermostClient.GetOldClientConfig(context.Background(), "")
	if err != nil {
		app.logger.Fatal().Err(err).Msg("Could not get server config")
	} else {
		app.logger.Info().Interface("clientConfig", clientConfig).Msg("Got server config")
	}
	app.clientConfig = clientConfig

	// Build router and start HTTP server.
	app.initializeAPI()
	startHTTPServer(app)

	// Listen to live events coming in via websocket.
	listenToEvents(app)
}

func startHTTPServer(app *application) {
	server := &http.Server{
		Addr:              app.config.httpAddr,
		Handler:           app,
		ReadHeaderTimeout: 10 * time.Second,
	}

	go func() {
		app.logger.Info().
			Str("addr", app.config.httpAddr).
			Str("public_url", app.config.botPublicURL).
			Msg("HTTP server listening")
		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			app.logger.Error().Err(err).Msg("HTTP server failed")
		}
	}()
}

func setupGracefulShutdown(app *application) {
	c := make(chan os.Signal, 1)
	signal.Notify(c, os.Interrupt)
	go func() {
		for range c {
			if app.mattermostWebSocketClient != nil {
				app.logger.Info().Msg("Closing websocket connection")
				app.mattermostWebSocketClient.Close()
			}
			app.logger.Info().Msg("Shutting down")
			os.Exit(0)
		}
	}()
}

func sendMsgToTalkingChannel(app *application, msg string, channelId string, replyToId string) {
	// Note that replyToId should be empty for a new post.
	// All replies in a thread should reply to root.

	post := &model.Post{}
	post.ChannelId = channelId
	post.Message = msg

	post.RootId = replyToId

	if _, _, err := app.mattermostClient.CreatePost(context.Background(), post); err != nil {
		app.logger.Error().Err(err).Str("RootID", replyToId).Msg("Failed to create post")
	}
}

func listenToEvents(app *application) {
	var err error
	failCount := 0

	wsscheme := "ws://%s"
	if app.config.mattermostServer.Scheme == "https" {
		wsscheme = "wss://%s"
	}

	for {
		wsURL := fmt.Sprintf(wsscheme, app.config.mattermostServer.Host+app.config.mattermostServer.Path)
		dialer := websocket.DefaultDialer
		if app.config.SkipVerify {
			dialer = &websocket.Dialer{
				HandshakeTimeout: 10 * time.Second,
				TLSClientConfig:  &tls.Config{InsecureSkipVerify: true},
			}
		}
		app.mattermostWebSocketClient, err = model.NewWebSocketClient4WithDialer(dialer, wsURL, app.mattermostClient.AuthToken)
		if err != nil {
			app.logger.Warn().Err(err).Msg("Mattermost websocket disconnected, retrying")
			failCount += 1
			// TODO: backoff based on failCount and sleep for a while.
			continue
		}
		app.logger.Info().Msg("Mattermost websocket connected")

		app.mattermostWebSocketClient.Listen()

		for event := range app.mattermostWebSocketClient.EventChannel {
			// Launch new goroutine for handling the actual event.
			// If required, you can limit the number of events beng processed at a time.
			go handleWebSocketEvent(app, event)
		}
	}
}

func handleWebSocketEvent(app *application, event *model.WebSocketEvent) {
	// Ignore other types of events.
	if event.EventType() != model.WebsocketEventPosted {
		return
	}

	// Since this event is a post, unmarshal it to (*model.Post)
	post := &model.Post{}
	err := json.Unmarshal([]byte(event.GetData()["post"].(string)), &post)
	if err != nil {
		app.logger.Error().Err(err).Msg("Could not cast event to *model.Post")
	}

	// Ignore messages sent by this bot itself.
	if post.UserId == app.mattermostUser.Id {
		return
	}

	// Handle however you want.
	handlePost(app, post)
}

func handlePost(app *application, post *model.Post) {
	app.logger.Debug().Str("message", post.Message).Msg("")
	app.logger.Debug().Interface("post", post).Msg("")

	channel, _, err := app.mattermostClient.GetChannel(context.Background(), post.ChannelId, "")
	if err != nil {
		app.logger.Error().Err(err).Msg("Could not get channel")
		return
	}

	if matched, _ := regexp.MatchString(`(?:^|\W)hello(?:$|\W)`, post.Message); matched {
		replyToId := post.Id
		msg := "Ответ на сообщение."
		if post.RootId != "" {
			replyToId = post.RootId
			msg = "Ответ на сообщение в трэде."
		}

		sendMsgToTalkingChannel(app, msg, channel.Id, replyToId)
		return
	}

	if post.Message == "start" {
		msg := `Привет!
Это бот, который покажет примеры работы интерактивного бота.
Напишите боту или в канале, где присутствует бот:
start - пришлёт это сообщение'
hello - он ответит на приветствие
block - пришлёт сообщение с блоком
button - пришлёт сообщение с интерактивными кнопками`
		sendMsgToTalkingChannel(app, msg, channel.Id, "")
		return
	}

	if post.Message == "block" {
		newPost := &model.Post{}
		newPost.ChannelId = channel.Id
		newPost.RootId = post.Id
		newPost.Message = "Сообщение с блоком"
		attachment := &model.SlackAttachment{
			Text:       "Какой то текст",
			Fallback:   "Текст с отступом",
			Title:      "Заголовок",
			AuthorName: "@admin",
			Color:      "#FF0000",
		}

		newPost.AddProp(model.PostPropsAttachments, []*model.SlackAttachment{attachment})
		if _, _, err := app.mattermostClient.CreatePost(context.Background(), newPost); err != nil {
			app.logger.Error().Err(err).Str("RootID", post.Id).Msg("Failed to create post")
		}
	}

	if post.Message == "button" {
		newPost := &model.Post{}
		newPost.ChannelId = channel.Id
		newPost.RootId = post.Id
		newPost.Message = "This message with block"
		attachment := &model.SlackAttachment{
			Text: "Выберите действие",
			Actions: []*model.PostAction{
				{
					Id:    "accept", // этот параметр, на какой адрес будет слать браузер маттермосту http://localhost:8065/api/v4/posts/y5qk7yhy77bwbp3nfrzqmc7gqy/actions/accept
					Name:  "Принять",
					Type:  "button",
					Style: "primary",
					Integration: &model.PostActionIntegration{
						URL: fmt.Sprintf("%s/accept", app.config.botPublicURL), // этот урл, на который будет слать запрос маттермост этому боту. /accept должно быть в эндпоинтах
					},
				},
				{
					Id:    "decline",
					Name:  "Отклонить",
					Type:  "button",
					Style: "danger",
					Integration: &model.PostActionIntegration{
						URL: fmt.Sprintf("%s/decline", app.config.botPublicURL),
					},
				},
			},
		}

		newPost.AddProp(model.PostPropsAttachments, []*model.SlackAttachment{attachment})

		if _, _, err := app.mattermostClient.CreatePost(context.Background(), newPost); err != nil {
			app.logger.Error().Err(err).Str("RootID", post.Id).Msg("Failed to create post")
		}
	}
}
