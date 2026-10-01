package main

import (
	"context"
	"fmt"
	"net/http"
	"os"
	"time"
)

func main() {
	target := "http://127.0.0.1:5000/api/mobile/bootstrap"
	if len(os.Args) > 1 && os.Args[1] != "" {
		target = os.Args[1]
	}

	ctx, cancel := context.WithTimeout(context.Background(), 4*time.Second)
	defer cancel()

	request, err := http.NewRequestWithContext(ctx, http.MethodGet, target, nil)
	if err != nil {
		fail(err)
	}

	response, err := http.DefaultClient.Do(request)
	if err != nil {
		fail(err)
	}
	defer response.Body.Close()

	if response.StatusCode < http.StatusOK || response.StatusCode >= http.StatusMultipleChoices {
		fail(fmt.Errorf("unexpected status: %s", response.Status))
	}
}

func fail(err error) {
	fmt.Fprintln(os.Stderr, err)
	os.Exit(1)
}
