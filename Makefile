IMAGE      := localhost/wgi-sync
VIDEO_DIR  ?=
REMOTE     ?= little-willow
REMOTE_DIR ?= ~/wgi-video-sync
RUNTIME    ?= $(shell command -v podman >/dev/null 2>&1 && echo podman || echo docker)

# Lazily evaluated so VIDEO_DIR and RUNTIME expand at use time, not parse time
DOCKER      = $(RUNTIME) run --rm -v "$(VIDEO_DIR):/videos" $(IMAGE)
# For process/dry-run: mounts config.json from the project dir so no manual copy needed
DOCKER_PROC = $(RUNTIME) run --rm -v "$(VIDEO_DIR):/videos" -v "$(CURDIR)/config.json:/config.json:ro,z" $(IMAGE)

RSYNC_FILES := analyze.py process.py Makefile Dockerfile entrypoint.sh requirements.txt .dockerignore config.json

# ANSI colors via printf
RED    := \033[31m
GREEN  := \033[32m
YELLOW := \033[33m
CYAN   := \033[36m
BOLD   := \033[1m
DIM    := \033[2m
RESET  := \033[0m

.DEFAULT_GOAL := help

.PHONY: help build analyze process dry-run shell clean clean-all guard deploy

help:
	@printf '$(BOLD)WGI Video Sync$(RESET)\n'
	@printf '\n'
	@printf '$(BOLD)Usage:$(RESET)\n'
	@printf '  make $(CYAN)<target>$(RESET) $(YELLOW)VIDEO_DIR$(RESET)=/path/to/videos\n'
	@printf '\n'
	@printf '$(BOLD)Targets:$(RESET)\n'
	@printf '  $(CYAN)build$(RESET)      Build the Docker image\n'
	@printf '  $(CYAN)analyze$(RESET)    Scan videos and write config.json $(DIM)(run first)$(RESET)\n'
	@printf '  $(CYAN)process$(RESET)    Cut segments and render title cards\n'
	@printf '  $(CYAN)dry-run$(RESET)    Show what process would do without touching video\n'
	@printf '  $(CYAN)shell$(RESET)      Drop into a bash shell in the container\n'
	@printf '  $(CYAN)deploy$(RESET)     Rsync scripts to little-willow\n'
	@printf '  $(CYAN)clean$(RESET)      Remove output/ directory\n'
	@printf '  $(CYAN)clean-all$(RESET)  Remove output/ and config.json\n'
	@printf '\n'
	@printf '$(BOLD)Optional vars:$(RESET)\n'
	@printf '  $(YELLOW)THRESHOLD$(RESET)=0.3              Scene sensitivity for analyze $(DIM)(default 0.35)$(RESET)\n'
	@printf '  $(YELLOW)MIN_GAP$(RESET)=120                Min quiet seconds between performances $(DIM)(default 90)$(RESET)\n'
	@printf '  $(YELLOW)ONLY$(RESET)="buckhorn"            Process only matching band name\n'
	@printf '  $(YELLOW)REMOTE$(RESET)=little-willow       Deploy host $(DIM)(default: little-willow)$(RESET)\n'
	@printf '  $(YELLOW)REMOTE_DIR$(RESET)=~/wgi-video-sync  Deploy path $(DIM)(default: ~/wgi-video-sync)$(RESET)\n'
	@printf '  $(YELLOW)RUNTIME$(RESET)=podman             Container runtime $(DIM)(default: docker)$(RESET)\n'
	@printf '\n'
	@printf '$(DIM)Tip: export VIDEO_DIR=/path/to/videos to avoid repeating it$(RESET)\n'

guard:
	@test -n "$(VIDEO_DIR)" || \
	  (printf '$(RED)Error: VIDEO_DIR is not set.$(RESET)\n' && \
	   printf 'Usage: make <target> $(YELLOW)VIDEO_DIR$(RESET)=/path/to/videos\n' && exit 1)

build:
	@printf '$(CYAN)Building image $(BOLD)$(IMAGE)$(RESET) $(DIM)(runtime: $(RUNTIME))$(RESET)\n'
	@$(RUNTIME) build -q -t $(IMAGE) . > /dev/null
	@printf '$(GREEN)Image built: $(BOLD)$(IMAGE)$(RESET)\n'

analyze: guard
	@printf '$(CYAN)Analyzing$(RESET) $(BOLD)$(VIDEO_DIR)$(RESET)\n'
	$(DOCKER) analyze /videos \
	  $(if $(THRESHOLD),--threshold $(THRESHOLD)) \
	  $(if $(MIN_GAP),--min-gap $(MIN_GAP))

process: guard
	@printf '$(CYAN)Processing$(RESET) $(BOLD)$(CURDIR)/config.json$(RESET)\n'
	$(DOCKER_PROC) process /config.json \
	  $(if $(ONLY),--only "$(ONLY)") \
	  $(if $(SKIP_EXISTING),--skip-existing)

dry-run: guard
	@printf '$(DIM)Dry run --$(RESET) $(BOLD)$(CURDIR)/config.json$(RESET)\n'
	$(DOCKER_PROC) process /config.json --dry-run \
	  $(if $(ONLY),--only "$(ONLY)") \
	  $(if $(SKIP_EXISTING),--skip-existing)

shell: guard
	@printf '$(CYAN)Opening shell in container$(RESET) $(DIM)(VIDEO_DIR mounted at /videos)$(RESET)\n'
	@$(RUNTIME) run --rm -it \
	  -v "$(VIDEO_DIR):/videos" \
	  --entrypoint bash \
	  $(IMAGE)

deploy:
	@printf '$(CYAN)Deploying to$(RESET) $(BOLD)$(REMOTE):$(REMOTE_DIR)$(RESET)\n'
	@ssh $(REMOTE) "mkdir -p $(REMOTE_DIR)"
	@rsync -avz --progress $(RSYNC_FILES) $(REMOTE):$(REMOTE_DIR)/
	@ssh $(REMOTE) "chmod 644 $(REMOTE_DIR)/config.json"
	@printf '$(CYAN)Rebuilding image on$(RESET) $(BOLD)$(REMOTE)$(RESET)\n'
	@ssh $(REMOTE) "cd $(REMOTE_DIR) && make build"
	@printf '$(GREEN)Deployed to $(BOLD)$(REMOTE):$(REMOTE_DIR)$(RESET)\n'

clean: guard
	@printf '$(YELLOW)Removing$(RESET) $(VIDEO_DIR)/output\n'
	@rm -rf "$(VIDEO_DIR)/output"
	@printf '$(GREEN)Done$(RESET)\n'

clean-all: guard
	@printf '$(YELLOW)Removing$(RESET) $(VIDEO_DIR)/output and config.json\n'
	@rm -rf "$(VIDEO_DIR)/output"
	@rm -f "$(VIDEO_DIR)/config.json"
	@printf '$(GREEN)Done$(RESET)\n'
