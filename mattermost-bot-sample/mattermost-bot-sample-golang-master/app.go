package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"time"

	"github.com/gorilla/mux"
	"github.com/mattermost/mattermost/server/public/model"
	"github.com/rs/zerolog"
)

// application struct to hold the dependencies for our bot
type application struct {
	config                    config
	clientConfig              map[string]string
	logger                    zerolog.Logger
	mattermostClient          *model.Client4
	mattermostWebSocketClient *model.WebSocketClient
	mattermostUser            *model.User
	router                    *mux.Router
}

// initializeAPI builds the HTTP router, mirroring the style used in
// mattermost plugins (see plugin.MattermostPlugin.ServeHTTP + mux.Router).
func (app *application) initializeAPI() {
	r := mux.NewRouter()
	r.Use(app.withRecovery)
	r.Use(app.withLogging)

	// Health/demo endpoint.
	r.HandleFunc("/healthcheck", app.handleHello).Methods(http.MethodGet)

	// Interactive message actions. Mattermost POSTs PostActionIntegrationRequest
	// to these URLs and expects a PostActionIntegrationResponse back.
	r.HandleFunc("/accept", app.handleAccept).Methods(http.MethodPost)
	r.HandleFunc("/decline", app.handleDecline).Methods(http.MethodPost)

	r.NotFoundHandler = http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.NotFound(w, r)
	})

	app.router = r
}

// ServeHTTP delegates to the initialized router.
func (app *application) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if app.router == nil {
		http.Error(w, "router not initialized", http.StatusInternalServerError)
		return
	}
	app.router.ServeHTTP(w, r)
}

// --- middlewares ---

func (app *application) withLogging(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		sw := &statusWriter{ResponseWriter: w, status: http.StatusOK}
		next.ServeHTTP(sw, r)
		app.logger.Info().
			Str("method", r.Method).
			Str("path", r.URL.Path).
			Int("status", sw.status).
			Dur("duration", time.Since(start)).
			Str("remote", r.RemoteAddr).
			Msg("http request")
	})
}

func (app *application) withRecovery(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer func() {
			if rec := recover(); rec != nil {
				app.logger.Error().
					Interface("panic", rec).
					Str("path", r.URL.Path).
					Msg("recovered from panic in HTTP handler")
				http.Error(w, "internal server error", http.StatusInternalServerError)
			}
		}()
		next.ServeHTTP(w, r)
	})
}

type statusWriter struct {
	http.ResponseWriter
	status int
}

func (sw *statusWriter) WriteHeader(code int) {
	sw.status = code
	sw.ResponseWriter.WriteHeader(code)
}

// --- handlers ---

func (app *application) handleHello(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "text/plain; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	fmt.Fprintln(w, "Hello, world!")
}

func (app *application) handleAccept(w http.ResponseWriter, r *http.Request) {
	app.handleAction(w, r, "accept")
}

func (app *application) handleDecline(w http.ResponseWriter, r *http.Request) {
	app.handleAction(w, r, "decline")
}

// handleAction handles interactive button callbacks from mattermost.
// Mattermost sends POST <url> with a PostActionIntegrationRequest body
// and expects a PostActionIntegrationResponse in reply.
func (app *application) handleAction(w http.ResponseWriter, r *http.Request, action string) {
	var req model.PostActionIntegrationRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		app.logger.Error().Err(err).Str("action", action).Msg("failed to decode action request")
		writeActionError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	defer r.Body.Close()

	app.logger.Info().
		Str("action", action).
		Str("user_id", req.UserId).
		Str("channel_id", req.ChannelId).
		Str("post_id", req.PostId).
		Msg("interactive action received")

	var msg string
	switch action {
	case "accept":
		msg = fmt.Sprintf("<@%s> принял запрос.", req.UserId)
	case "decline":
		msg = fmt.Sprintf("<@%s> отклонил запрос.", req.UserId)
	default:
		msg = fmt.Sprintf("<@%s> выполнил действие %q.", req.UserId, action)
	}

	sendMsgToTalkingChannel(app, msg, req.ChannelId, req.PostId)

	writeActionResponse(w, &model.PostActionIntegrationResponse{
		EphemeralText: fmt.Sprintf("Действие %q обработано.", action),
	})
}

func writeActionResponse(w http.ResponseWriter, resp *model.PostActionIntegrationResponse) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(resp)
}

func writeActionError(w http.ResponseWriter, status int, text string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(&model.PostActionIntegrationResponse{
		EphemeralText: text,
	})
}
