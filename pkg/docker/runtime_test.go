package docker

import (
	"strings"
	"testing"
)

func TestContainerRuntimeFromEnv(t *testing.T) {
	cases := map[string]string{
		"":         "",
		"   ":      "",
		"runsc":    "runsc",
		" runsc\n": "runsc",
		"runc":     "runc",
	}
	for in, want := range cases {
		got := containerRuntimeFromEnv(func(k string) string {
			if k != ContainerRuntimeEnv {
				t.Fatalf("unexpected env lookup %q", k)
			}
			return in
		})
		if got != want {
			t.Errorf("containerRuntimeFromEnv(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestCheckRuntimeAvailable(t *testing.T) {
	avail := []string{"runc", "io.containerd.runc.v2", "runsc"}

	if err := checkRuntimeAvailable("", avail); err != nil {
		t.Errorf("empty runtime (default) must always be accepted, got %v", err)
	}
	if err := checkRuntimeAvailable("", nil); err != nil {
		t.Errorf("empty runtime must not depend on the daemon, got %v", err)
	}
	if err := checkRuntimeAvailable("runsc", avail); err != nil {
		t.Errorf("runsc is registered, got %v", err)
	}
	err := checkRuntimeAvailable("kata", avail)
	if err == nil || !strings.Contains(err.Error(), "kata") || !strings.Contains(err.Error(), "runsc") {
		t.Errorf("expected error naming the missing and available runtimes, got %v", err)
	}
}

func TestHandlerHostConfig(t *testing.T) {
	hc := handlerHostConfig("fn-net", "")
	if hc.Runtime != "" {
		t.Errorf("default must leave Runtime empty so Docker uses its default, got %q", hc.Runtime)
	}
	if string(hc.NetworkMode) != "fn-net" {
		t.Errorf("NetworkMode = %q, want fn-net", hc.NetworkMode)
	}
	if hc := handlerHostConfig("fn-net", "runsc"); hc.Runtime != "runsc" {
		t.Errorf("Runtime = %q, want runsc", hc.Runtime)
	}
}
