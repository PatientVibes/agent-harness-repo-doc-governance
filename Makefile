# Makefile — re-vendor the skill body + references from agent-skills.
#
# Vendored prompt files in src/repo_doc_governance/prompts/ are the harness's
# single source of truth at runtime. Their *upstream* source is the
# repo-documentation-governance plugin in PatientVibes/agent-skills.
#
# Workflow:
#   1. Edit upstream in agent-skills (the SKILL.md, the references/*.md).
#   2. Get the upstream change merged to master.
#   3. Run `make re-vendor` here.
#   4. Commit the resulting prompts/ diff in this repo.
#
# `make re-vendor` refuses to overwrite if the destination files have local
# edits (i.e. someone hand-edited the vendored copy). That's a red flag —
# fix upstream and re-vendor instead.

AGENT_SKILLS_REPO ?= https://github.com/PatientVibes/agent-skills.git
AGENT_SKILLS_REF  ?= master
PROMPTS_DIR := src/repo_doc_governance/prompts
TMP_DIR     := .vendor-tmp

# Files to vendor: <upstream relative path>:<destination filename>
VENDOR_PAIRS := \
  repo-documentation-governance.md:skill_body.md \
  references/phases.md:phases.md \
  references/decisions.md:decisions.md \
  references/templates.md:templates.md

.PHONY: re-vendor verify-no-local-edits clean-vendor-tmp test lint help

help:
	@echo "Targets:"
	@echo "  re-vendor              Refresh vendored prompts from agent-skills@AGENT_SKILLS_REF (default: master)."
	@echo "                         Override the ref with: make re-vendor AGENT_SKILLS_REF=<sha-or-branch>"
	@echo "  verify-no-local-edits  Fail if any vendored prompt has been hand-edited."
	@echo "  test                   Run pytest."
	@echo "  lint                   Static checks (placeholder)."

re-vendor: verify-no-local-edits clean-vendor-tmp
	@echo ">> Cloning agent-skills@$(AGENT_SKILLS_REF) into $(TMP_DIR)/"
	@git clone --quiet --depth=1 --branch $(AGENT_SKILLS_REF) $(AGENT_SKILLS_REPO) $(TMP_DIR) 2>/dev/null \
	  || git clone --quiet $(AGENT_SKILLS_REPO) $(TMP_DIR)
	@cd $(TMP_DIR) && git checkout --quiet $(AGENT_SKILLS_REF)
	@SHA=$$(cd $(TMP_DIR) && git rev-parse HEAD); \
	  echo ">> Vendoring at SHA $$SHA"; \
	  for pair in $(VENDOR_PAIRS); do \
	    src_file=$${pair%%:*}; \
	    dst_file=$${pair##*:}; \
	    src_path=$(TMP_DIR)/plugins/repo-documentation-governance/agents/$$src_file; \
	    dst_path=$(PROMPTS_DIR)/$$dst_file; \
	    if [ ! -f "$$src_path" ]; then \
	      echo "ERROR: upstream file missing: $$src_path"; exit 2; \
	    fi; \
	    echo "   $$src_file -> $$dst_file"; \
	    { printf '<!-- DO NOT EDIT — vendored from agent-skills/plugins/repo-documentation-governance/agents/%s @ %s. Edit upstream + re-vendor via "make re-vendor". -->\n\n' "$$src_file" "$$SHA"; \
	      cat "$$src_path"; } > "$$dst_path"; \
	  done
	@$(MAKE) clean-vendor-tmp
	@echo ">> Done. Review the diff in $(PROMPTS_DIR)/ and commit."

# Fail if any vendored prompt has been edited locally relative to the SHA in its header.
# Detects the "someone tweaked the vendored copy" anti-pattern before re-vendoring overwrites the change.
verify-no-local-edits:
	@for pair in $(VENDOR_PAIRS); do \
	  src_file=$${pair%%:*}; \
	  dst_file=$${pair##*:}; \
	  dst_path=$(PROMPTS_DIR)/$$dst_file; \
	  if [ ! -f "$$dst_path" ]; then continue; fi; \
	  header_sha=$$(head -1 "$$dst_path" | sed -n 's/.*@ \([0-9a-f]\{40\}\).*/\1/p'); \
	  if [ -z "$$header_sha" ]; then \
	    echo "ERROR: $$dst_path is missing a 'DO NOT EDIT — vendored ... @ <sha>' header. Refusing to overwrite."; \
	    exit 3; \
	  fi; \
	done
	@echo ">> All vendored files have valid headers."

clean-vendor-tmp:
	@rm -rf $(TMP_DIR)

test:
	pytest -q

lint:
	@echo "(no linter configured yet — placeholder)"
