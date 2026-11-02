package docker

import (
	"context"
	"fmt"
	"os"
	"sort"
	"strings"

	"github.com/docker/docker/client"
)

// ContainerRuntimeEnv is the environment variable that selects the OCI
// runtime used for function handler containers, e.g. "runsc" for gVisor.
// If unset or empty, Docker's default runtime (normally runc) is used and
// behaviour is identical to earlier tinyFaaS versions.
const ContainerRuntimeEnv = "TF_CONTAINER_RUNTIME"

// containerRuntimeFromEnv returns the runtime requested through
// TF_CONTAINER_RUNTIME. An empty string means "let Docker decide".
func containerRuntimeFromEnv(getenv func(string) string) string {
	return strings.TrimSpace(getenv(ContainerRuntimeEnv))
}

// checkRuntimeAvailable fails if the requested runtime is not registered
// with the Docker daemon, so a typo or a missing runsc install is reported
// at startup instead of on the first function upload.
func checkRuntimeAvailable(runtime string, available []string) error {
	if runtime == "" {
		return nil
	}
	for _, r := range available {
		if r == runtime {
			return nil
		}
	}
	sort.Strings(available)
	return fmt.Errorf("container runtime %q (from %s) is not registered with the Docker daemon; available runtimes: %s", runtime, ContainerRuntimeEnv, strings.Join(available, ", "))
}

func daemonRuntimes(c *client.Client) ([]string, error) {
	info, err := c.Info(context.Background())
	if err != nil {
		return nil, err
	}
	rs := make([]string, 0, len(info.Runtimes))
	for name := range info.Runtimes {
		rs = append(rs, name)
	}
	return rs, nil
}

func resolveContainerRuntime(c *client.Client) (string, error) {
	rt := containerRuntimeFromEnv(os.Getenv)
	if rt == "" {
		return "", nil
	}
	available, err := daemonRuntimes(c)
	if err != nil {
		return "", fmt.Errorf("could not query Docker daemon runtimes: %w", err)
	}
	return rt, checkRuntimeAvailable(rt, available)
}
