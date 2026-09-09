PREFIX ?= $(HOME)/.local
BINDIR := $(PREFIX)/bin
TARGET := $(BINDIR)/agenttop
SOURCE := $(abspath agenttop)
PYTHON ?= python3

.PHONY: install uninstall check test

install:
	@mkdir -p $(BINDIR)
	@if [ -e "$(TARGET)" ] && [ ! -L "$(TARGET)" ]; then \
		mv "$(TARGET)" "$(TARGET).bak"; \
		echo "existing file moved to $(TARGET).bak"; \
	fi
	@ln -sfn "$(SOURCE)" "$(TARGET)"
	@echo "linked $(TARGET) -> $(SOURCE)"

uninstall:
	@if [ -L "$(TARGET)" ]; then rm "$(TARGET)"; echo "removed $(TARGET)"; fi

check:
	@$(PYTHON) -c "import ast; ast.parse(open('agenttop').read())" && echo "syntax ok"
	@$(PYTHON) -m unittest discover -s tests -q
	@$(PYTHON) agenttop --json > /dev/null && echo "json snapshot ok"

test:
	@$(PYTHON) -m unittest discover -s tests -v
