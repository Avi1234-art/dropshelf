#include <Python.h>
#include <mach-o/dyld.h>

#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static int dirname_copy(const char *path, char *out, size_t out_size) {
    size_t len;
    char *slash;

    if (path == NULL || out == NULL || out_size == 0) {
        return -1;
    }

    len = strnlen(path, out_size);
    if (len >= out_size) {
        return -1;
    }

    memcpy(out, path, len + 1);
    slash = strrchr(out, '/');
    if (slash == NULL) {
        return -1;
    }
    *slash = '\0';
    return 0;
}

static int make_path(char *out, size_t out_size, const char *left, const char *right) {
    int written;

    if (out == NULL || left == NULL || right == NULL || out_size == 0) {
        return -1;
    }

    written = snprintf(out, out_size, "%s/%s", left, right);
    if (written < 0 || (size_t) written >= out_size) {
        return -1;
    }
    return 0;
}

static void setup_logging(void) {
    const char *home = getenv("HOME");
    char support_dir[PATH_MAX];
    char log_path[PATH_MAX];

    if (home == NULL || home[0] == '\0') {
        return;
    }

    if (snprintf(support_dir, sizeof(support_dir), "%s/.dropshelf", home) >= (int) sizeof(support_dir)) {
        return;
    }
    mkdir(support_dir, 0755);

    if (snprintf(log_path, sizeof(log_path), "%s/app.log", support_dir) >= (int) sizeof(log_path)) {
        return;
    }

    if (freopen(log_path, "a", stdout) == NULL) {
        return;
    }
    if (freopen(log_path, "a", stderr) == NULL) {
        return;
    }

    setvbuf(stdout, NULL, _IOLBF, 0);
    setvbuf(stderr, NULL, _IONBF, 0);
}

int main(int argc, char **argv) {
    uint32_t exec_size = PATH_MAX;
    char exec_path[PATH_MAX];
    char resolved_exec[PATH_MAX];
    char macos_dir[PATH_MAX];
    char resources_dir[PATH_MAX];
    char resolved_resources[PATH_MAX];
    char script_path[PATH_MAX];
    char **python_argv;
    int i;
    int python_argc;

    setup_logging();

    if (_NSGetExecutablePath(exec_path, &exec_size) != 0) {
        fprintf(stderr, "Could not determine launcher path.\n");
        return 1;
    }

    if (realpath(exec_path, resolved_exec) == NULL) {
        if (strlcpy(resolved_exec, exec_path, sizeof(resolved_exec)) >= sizeof(resolved_exec)) {
            fprintf(stderr, "Launcher path is too long.\n");
            return 1;
        }
    }

    if (dirname_copy(resolved_exec, macos_dir, sizeof(macos_dir)) != 0) {
        fprintf(stderr, "Could not resolve app MacOS directory.\n");
        return 1;
    }

    if (make_path(resources_dir, sizeof(resources_dir), macos_dir, "../Resources") != 0) {
        fprintf(stderr, "Could not resolve app Resources directory.\n");
        return 1;
    }

    if (realpath(resources_dir, resolved_resources) == NULL) {
        if (strlcpy(resolved_resources, resources_dir, sizeof(resolved_resources)) >= sizeof(resolved_resources)) {
            fprintf(stderr, "Resources path is too long.\n");
            return 1;
        }
    }

    if (make_path(script_path, sizeof(script_path), resolved_resources, "dropshelf.py") != 0) {
        fprintf(stderr, "Could not resolve app script path.\n");
        return 1;
    }

    if (access(script_path, R_OK) != 0) {
        fprintf(stderr, "Could not read %s\n", script_path);
        return 1;
    }

    python_argc = argc + 1;
    python_argv = calloc((size_t) python_argc + 1, sizeof(char *));
    if (python_argv == NULL) {
        fprintf(stderr, "Could not allocate argument list.\n");
        return 1;
    }

    python_argv[0] = resolved_exec;
    python_argv[1] = script_path;
    for (i = 1; i < argc; ++i) {
        python_argv[i + 1] = argv[i];
    }
    python_argv[python_argc] = NULL;

    return Py_BytesMain(python_argc, python_argv);
}
