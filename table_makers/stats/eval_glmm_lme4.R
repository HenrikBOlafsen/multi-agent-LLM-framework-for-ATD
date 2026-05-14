#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)

if (length(args) != 2) {
  cat("Usage: Rscript eval_glmm_lme4.R <input_csv> <outdir>\n", file = stderr())
  quit(status = 2)
}

suppressPackageStartupMessages({
  library(lme4)
})

input_csv <- args[1]
outdir <- args[2]
dir.create(outdir, recursive = TRUE, showWarnings = FALSE)

die <- function(msg) {
  cat(paste0("ERROR: ", msg, "\n"), file = stderr())
  quit(status = 2)
}

fmt_p <- function(p) {
  if (is.na(p)) return(NA_character_)
  if (p < 0.001) return("<0.001")
  sprintf("%.3f", p)
}

fmt_ci <- function(lo, hi, digits = 3) {
  if (is.na(lo) || is.na(hi)) return(NA_character_)
  paste0(round(lo, digits), "--", round(hi, digits))
}

or_ci_wald <- function(beta, se) {
  c(
    or = exp(beta),
    lo = exp(beta - 1.96 * se),
    hi = exp(beta + 1.96 * se)
  )
}

fit_glmm <- function(formula, data) {
  glmer(
    formula,
    data = data,
    family = binomial(link = "logit"),
    control = glmerControl(
      optimizer = "bobyqa",
      optCtrl = list(maxfun = 2e5)
    )
  )
}

extract_var <- function(model, grouping) {
  vc <- as.data.frame(VarCorr(model))
  row <- vc[vc$grp == grouping, , drop = FALSE]
  if (nrow(row) == 0) return(NA_real_)
  row$vcov[1]
}

df <- read.csv(input_csv, stringsAsFactors = FALSE)

required <- c("repo", "cycle_id", "mode_id", "success")
missing <- setdiff(required, names(df))
if (length(missing) > 0) {
  die(paste0("missing required columns: ", paste(missing, collapse = ", ")))
}

df$success <- as.integer(df$success != 0)
df$cycle <- factor(paste(df$repo, df$cycle_id, sep = "::"))
df$repo_factor <- factor(df$repo)

modes <- unique(df$mode_id)

if (!("no_explain" %in% modes)) {
  die("expected one mode_id to be 'no_explain'")
}

non_baseline <- setdiff(modes, "no_explain")

if (length(non_baseline) != 1) {
  die("expected exactly one non-baseline mode")
}

selected_mode <- non_baseline[1]
df$selected_system <- as.integer(df$mode_id == selected_mode)

cycle_mode <- aggregate(
  success ~ repo + cycle_id + cycle + repo_factor + mode_id + selected_system,
  data = df,
  FUN = function(x) c(successes = sum(x), trials = length(x))
)

cycle_mode$successes <- cycle_mode$success[, "successes"]
cycle_mode$trials <- cycle_mode$success[, "trials"]
cycle_mode$failures <- cycle_mode$trials - cycle_mode$successes
cycle_mode$success <- NULL

cat(sprintf("[eval-glmm] cycle-configuration rows: %d\n", nrow(cycle_mode)), file = stderr())
cat(sprintf("[eval-glmm] cycles represented: %d\n", length(unique(cycle_mode$cycle))), file = stderr())

m0 <- fit_glmm(
  cbind(successes, failures) ~ 1 + (1 | cycle),
  cycle_mode
)

m1 <- fit_glmm(
  cbind(successes, failures) ~ selected_system + (1 | cycle),
  cycle_mode
)

config_p <- anova(m0, m1, test = "Chisq")$`Pr(>Chisq)`[2]

cf <- summary(m1)$coefficients

config_beta <- cf["selected_system", "Estimate"]
config_se <- cf["selected_system", "Std. Error"]
config_or <- or_ci_wald(config_beta, config_se)

cycle_var <- extract_var(m1, "cycle")

robust_model <- tryCatch(
  fit_glmm(
    cbind(successes, failures) ~ selected_system + (1 | repo_factor) + (1 | cycle),
    cycle_mode
  ),
  error = function(e) {
    cat(paste0("[eval-glmm] robustness model failed: ", conditionMessage(e), "\n"), file = stderr())
    NULL
  }
)

repo_var <- if (is.null(robust_model)) NA_real_ else extract_var(robust_model, "repo_factor")

out <- data.frame(
  Effect = c(
    "Configuration (Advisory)",
    "Cycle random-effect variance",
    "Repository random-effect variance (robustness model)"
  ),
  Coefficient = c(
    round(config_beta, 3),
    round(cycle_var, 3),
    round(repo_var, 3)
  ),
  Odds_ratio = c(
    round(config_or["or"], 3),
    NA_real_,
    NA_real_
  ),
  CI_95_odds_ratio = c(
    fmt_ci(config_or["lo"], config_or["hi"]),
    NA_character_,
    NA_character_
  ),
  p = c(
    fmt_p(config_p),
    NA_character_,
    NA_character_
  ),
  stringsAsFactors = FALSE
)

write.csv(
  out,
  file.path(outdir, "eval_regression.csv"),
  row.names = FALSE
)

cat("[eval-glmm] wrote eval_regression.csv\n", file = stderr())