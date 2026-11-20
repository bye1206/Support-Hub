package main

import (
	"net/url"
	"os"

	_ "github.com/joho/godotenv/autoload"
)

type config struct {
	mattermostUserName string
	mattermostTeamName string
	mattermostToken    string
	mattermostChannel  string
	mattermostServer   *url.URL
	SkipVerify         bool
	httpAddr           string
	botPublicURL       string
}

func loadConfig() config {
	var settings config

	settings.mattermostTeamName = os.Getenv("MM_TEAM")
	settings.mattermostUserName = os.Getenv("MM_USERNAME")
	settings.mattermostToken = os.Getenv("MM_TOKEN")
	settings.mattermostChannel = os.Getenv("MM_CHANNEL")
	settings.mattermostServer, _ = url.Parse(os.Getenv("MM_SERVER"))

	if os.Getenv("SSL_SKIP_VERIFY") == "true" {
		settings.SkipVerify = true
	}

	settings.httpAddr = os.Getenv("HTTP_ADDR")
	if settings.httpAddr == "" {
		settings.httpAddr = ":8080"
	}

	settings.botPublicURL = os.Getenv("BOT_PUBLIC_URL")
	if settings.botPublicURL == "" {
		settings.botPublicURL = "http://localhost" + settings.httpAddr
	}

	return settings
}
