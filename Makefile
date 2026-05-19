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
# `make re-vendor` refuses to overwrite if any destination file's body
# (line 2 onward, skipping the DO-NOT-EDIT header) differs from upstream
# at the SHA recorded in its header. That catches the "someone hand-edited
# the vendored copy after vendoring" anti-pattern — re-vendoring would
# silently overwrite those edits. Surfaces the changed files and stops.

AGENT_SKILLS_REPO ?= https://github.com/PatientVibes/agent-skills.git
AGENT_SKILLS_REF  ?= master
PROMPTS_DIR := src/repo_doc_governance/prompts
TMP_DIR     := .vendor-tmp
VERIFY_TMP  := .vendor-verify-tmp

# Files to vendor: <upstream relative path>:<destination filename>
VENDOR_PAIRS := \
  repo-documentation-governance.md:skill_body.md \
  references/phases.md:phases.md \
  references/decisions.md:decisions.md \
  references/templates.md:templates.md

# Number of header lines on each vendored file (DO-NOT-EDIT comment + blank line).
# Bumping this requires updating both `re-vendor` (printf format) and the
# `tail -n +N` arithmetic in `verify-no-local-edits`.
HEADER_LINES := 2

.PHONY: re-vendor verify-no-local-edits clean-vendor-tmp clean-verify-tmp test lint help

help:
	@echo "Targets:"
	@echo "  re-vendor              Refresh vendored prompts from agent-skills@AGENT_SKILLS_REF (default: master)."
	@echo "                         Override the ref with: make re-vendor AGENT_SKILLS_REF=<sha-or-branch>"
	@echo "  verify-no-local-edits  Fail if any vendored prompt body has drifted from its recorded upstream SHA."
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

# Compare each destination's body (line $(HEADER_LINES)+1 onward) against the upstream
# content at the SHA recorded in its DO-NOT-EDIT header. Refuses to proceed if any
# vendored file has drifted — that is the failure mode this target exists to catch.
verify-no-local-edits: clean-verify-tmp
	@drift=0; \
	  vc_dirs=""; \
	  for pair in $(VENDOR_PAIRS); do \
	    src_file=$${pair%%:*}; \
	    dst_file=$${pair##*:}; \
	    dst_path=$(PROMPTS_DIR)/$$dst_file; \
	    if [ ! -f "$$dst_path" ]; then continue; fi; \
	    header_sha=$$(head -1 "$$dst_path" | sed -n 's/.*@ \([0-9a-f]\{40\}\).*/\1/p'); \
	    if [ -z "$$header_sha" ]; then \
	      echo "ERROR: $$dst_path is missing a 'DO NOT EDIT — vendored ... @ <sha>' header. Refusing to proceed."; \
	      exit 3; \
	    fi; \
	    vc_dir="$(VERIFY_TMP)/$$header_sha"; \
	    if [ ! -d "$$vc_dir" ]; then \
	      mkdir -p "$$vc_dir"; \
	      echo ">> Fetching agent-skills @ $$header_sha (drift check)"; \
	      git clone --quiet $(AGENT_SKILLS_REPO) "$$vc_dir" 2>/dev/null; \
	      (cd "$$vc_dir" && git checkout --quiet "$$header_sha") || { \
	        echo "ERROR: cannot check out $$header_sha in $$vc_dir. Refusing to proceed."; exit 4; \
	      }; \
	      vc_dirs="$$vc_dirs $$vc_dir"; \
	    fi; \
	    upstream="$$vc_dir/plugins/repo-documentation-governance/agents/$$src_file"; \
	    if [ ! -f "$$upstream" ]; then \
	      echo "ERROR: upstream file missing at $$header_sha: $$upstream. Refusing to proceed."; exit 5; \
	    fi; \
	    if ! cmp -s "$$upstream" <(tail -n +$$(( $(HEADER_LINES) + 1 )) "$$dst_path"); then \
	      echo "DRIFT: $$dst_path differs from agent-skills@$$header_sha:plugins/repo-documentation-governance/agents/$$src_file"; \
	      drift=1; \
	    fi; \
	  done; \
	  $(MAKE) clean-verify-tmp; \
	  if [ "$$drift" -ne 0 ]; then \
	    echo ""; \
	    echo "Vendored files have drifted from their recorded upstream SHA."; \
	    echo "Either:"; \
	    echo "  (a) Re-apply the local edits upstream in agent-skills, get them merged,"; \
	    echo "      then re-run 'make re-vendor' to pull them back in cleanly, OR"; \
	    echo "  (b) If the local edits are intentional (e.g. a hot-patch), document"; \
	    echo "      them in CHANGELOG and bypass with FORCE=1 — but this breaks the"; \
	    echo "      single-source-of-truth contract and should be a code-review red flag."; \
	    [ "$(FORCE)" = "1" ] || exit 6; \
	    echo "FORCE=1 set; proceeding despite drift."; \
	  fi; \
	  echo ">> All vendored files match their recorded upstream SHA."

clean-vendor-tmp:
	@rm -rf $(TMP_DIR)

clean-verify-tmp:
	@rm -rf $(VERIFY_TMP)

test:
	pytest -q

lint:
	@echo "(no linter configured yet — placeholder)"
