SHELL := /bin/bash

OMARCHY_PATH ?= /usr/share/omarchy
PLUGIN_ID := $(shell jq -r '.id' manifest.json)
PLUGIN_ROOT ?= $(HOME)/.config/omarchy/plugins
PLUGIN_DIR ?= $(PLUGIN_ROOT)/$(PLUGIN_ID)
QML_FILES := $(sort $(wildcard *.qml) $(wildcard */*.qml))
JS_FILES := $(sort $(wildcard *.js))

.DEFAULT_GOAL := help

.PHONY: help doctor check validate lint test format install-dev sync enable disable status summon hide logs watch uninstall-dev

help:
	@printf '%s\n' \
	  'Omarchy Pitchfork plugin' \
	  '' \
	  '  make doctor       Check the local toolchain and shell status' \
	  '  make check        Validate manifest, lint QML, run JS tests' \
	  '  make test         Run the pitch maths tests' \
	  '  make format       Format all QML files in place' \
	  '  make install-dev  Copy, discover, and enable the plugin' \
	  '  make sync         Validate and copy changes into Omarchy' \
	  '  make watch        Sync automatically whenever source changes' \
	  '  make summon       Open the Pitchfork panel' \
	  '  make hide         Close the Pitchfork panel' \
	  '  make status       Show the discovered plugin record' \
	  '  make logs         Tail recent Omarchy shell logs' \
	  '  make uninstall-dev Remove the development copy'

doctor:
	@./scripts/doctor.sh

check: validate lint test

validate:
	@./scripts/validate-plugin.sh

lint:
	qmllint -I "$(OMARCHY_PATH)/shell" $(QML_FILES)

# qmllint never opens a .js file, so without this a wrong tuning table -- or a
# Tunings.js that does not parse at all -- passes the whole verification gate.
test:
	@for file in $(JS_FILES); do node --check "$$file" || exit 1; done
	@node tests/tunings.test.mjs

format:
	qmlformat --inplace $(QML_FILES)

install-dev: check
	@OMARCHY_PLUGIN_DEV_ROOT="$(PLUGIN_ROOT)" ./scripts/sync-dev.sh "$(PLUGIN_DIR)"
	@if omarchy-shell shell ping >/dev/null 2>&1; then \
	  omarchy-shell shell rescanPlugins >/dev/null; \
	  omarchy plugin enable "$(PLUGIN_ID)"; \
	else \
	  printf '%s\n' 'Omarchy shell is not running; copied the plugin but did not enable it.' \
	    'Run make enable from a graphical Omarchy session.'; \
	fi

sync: check
	@OMARCHY_PLUGIN_DEV_ROOT="$(PLUGIN_ROOT)" ./scripts/sync-dev.sh "$(PLUGIN_DIR)"
	@omarchy-shell shell rescanPlugins >/dev/null 2>&1 || true

enable:
	omarchy plugin enable "$(PLUGIN_ID)"

disable:
	omarchy plugin disable "$(PLUGIN_ID)"

status:
	omarchy plugin list --json | jq --arg id "$(PLUGIN_ID)" '.[] | select(.id == $$id)'

summon:
	omarchy-shell shell summon "$(PLUGIN_ID)" '{}'

hide:
	omarchy-shell shell hide "$(PLUGIN_ID)"

logs:
	qs log -p "$(OMARCHY_PATH)/shell" --tail 100

watch:
	@OMARCHY_PLUGIN_DEV_ROOT="$(PLUGIN_ROOT)" ./scripts/watch-dev.sh "$(PLUGIN_DIR)"

uninstall-dev:
	omarchy plugin remove "$(PLUGIN_ID)" --yes
