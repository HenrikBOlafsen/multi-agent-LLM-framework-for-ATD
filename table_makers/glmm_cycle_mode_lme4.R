#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 3) {
  cat(
    paste0(
      "ERROR: Usage:\n",
      "  Rscript glmm_cycle_mode_lme4.R <input_csv> pairwise <reference_mode> <comparison_mode>\n",
      "  Rscript glmm_cycle_mode_lme4.R <input_csv> omnibus <mode1> <mode2> [<mode3> ...]\n"
    ),
    file = stderr()
  )
  quit(status = 2)
}

suppressPackageStartupMessages({
  library(lme4)
})

path <- args[1]
analysis_kind <- args[2]

die <- function(msg) {
  cat(paste0("ERROR: ", msg, "\n"), file = stderr())
  quit(status = 2)
}

to01 <- function(x) {
  if (is.logical(x)) return(as.integer(x))
  if (is.numeric(x)) return(as.integer(x != 0))
  xs <- tolower(trimws(as.character(x)))
  out <- rep(NA_integer_, length(xs))
  out[xs %in% c("true", "1", "yes", "y", "t")] <- 1L
  out[xs %in% c("false", "0", "no", "n", "f")] <- 0L
  out
}

emit_header <- function() {
  cat(
    paste(
      c(
        "analysis",
        "method",
        "reference_mode",
        "comparison_mode",
        "mode_levels",
        "n_mode",
        "n_obs",
        "converged",
        "singular",
        "beta",
        "se",
        "z",
        "wald_p_two_sided",
        "lrt_p",
        "odds_ratio",
        "or_ci_lo_95",
        "or_ci_hi_95",
        "n_cycle",
        "glmm_note"
      ),
      collapse = ","
    ),
    "\n",
    sep = ""
  )
}

emit_row <- function(
  analysis,
  method,
  reference_mode,
  comparison_mode,
  mode_levels,
  n_mode,
  n_obs,
  converged,
  singular,
  beta,
  se,
  z,
  wald_p_two_sided,
  lrt_p,
  odds_ratio,
  or_ci_lo_95,
  or_ci_hi_95,
  n_cycle,
  glmm_note
) {
  fmt <- function(x) {
    if (is.null(x) || length(x) == 0 || is.na(x)) return("NA")
    if (is.logical(x)) return(ifelse(x, "TRUE", "FALSE"))
    if (is.numeric(x)) return(sprintf("%.15g", x))
    return(as.character(x))
  }

  cat(
    paste(
      c(
        fmt(analysis),
        fmt(method),
        fmt(reference_mode),
        fmt(comparison_mode),
        fmt(mode_levels),
        fmt(n_mode),
        fmt(n_obs),
        fmt(converged),
        fmt(singular),
        fmt(beta),
        fmt(se),
        fmt(z),
        fmt(wald_p_two_sided),
        fmt(lrt_p),
        fmt(odds_ratio),
        fmt(or_ci_lo_95),
        fmt(or_ci_hi_95),
        fmt(n_cycle),
        fmt(glmm_note)
      ),
      collapse = ","
    ),
    "\n",
    sep = ""
  )
}

df <- tryCatch(
  read.csv(path, stringsAsFactors = FALSE),
  error = function(e) die(paste0("failed to read CSV: ", conditionMessage(e)))
)

need_cols <- c("repo", "cycle_id", "mode", "succ")
missing <- setdiff(need_cols, names(df))
if (length(missing) > 0) {
  die(paste0("missing required columns: ", paste(missing, collapse = ", ")))
}

df$succ <- to01(df$succ)
n_succ_na <- sum(is.na(df$succ))
df <- df[!is.na(df$succ), , drop = FALSE]
df$cycle <- as.factor(paste(df$repo, df$cycle_id, sep = "::"))

cat(sprintf("[glmm] loaded rows=%d from %s\n", nrow(df), path), file = stderr())
cat(sprintf("[glmm] rows after succ parse: %d (dropped succ NA=%d)\n", nrow(df), n_succ_na), file = stderr())

ctrl <- glmerControl(optimizer = "bobyqa", optCtrl = list(maxfun = 2e5))

emit_header()

if (analysis_kind == "pairwise") {
  if (length(args) != 4) {
    die("pairwise analysis requires exactly 2 mode arguments")
  }

  reference_mode <- args[3]
  comparison_mode <- args[4]
  mode_levels <- c(reference_mode, comparison_mode)

  dsub <- df[df$mode %in% mode_levels, , drop = FALSE]
  cat(
    sprintf(
      "[glmm] pairwise rows after mode filter (%s vs %s): %d\n",
      reference_mode, comparison_mode, nrow(dsub)
    ),
    file = stderr()
  )

  if (nrow(dsub) == 0) {
    emit_row(
      "pairwise",
      "lme4_glmer_cycle_RE",
      reference_mode,
      comparison_mode,
      paste(mode_levels, collapse = ";"),
      2,
      0,
      FALSE,
      NA,
      NA,
      NA,
      NA,
      NA,
      NA,
      NA,
      NA,
      NA,
      0,
      "no_rows_after_mode_filter"
    )
    quit(status = 0)
  }

  dsub$condition_bin <- ifelse(dsub$mode == comparison_mode, 1L, 0L)

  if (length(unique(dsub$condition_bin)) < 2) {
    emit_row(
      "pairwise",
      "lme4_glmer_cycle_RE",
      reference_mode,
      comparison_mode,
      paste(mode_levels, collapse = ";"),
      2,
      nrow(dsub),
      FALSE,
      NA,
      NA,
      NA,
      NA,
      NA,
      NA,
      NA,
      NA,
      NA,
      length(levels(dsub$cycle)),
      "only_one_mode_present_after_filter"
    )
    quit(status = 0)
  }

  m_full <- tryCatch(
    glmer(
      succ ~ condition_bin + (1 | cycle),
      data = dsub,
      family = binomial(link = "logit"),
      control = ctrl
    ),
    error = function(e) die(paste0("glmer(full pairwise) failed: ", conditionMessage(e)))
  )

  m_null <- tryCatch(
    glmer(
      succ ~ 1 + (1 | cycle),
      data = dsub,
      family = binomial(link = "logit"),
      control = ctrl
    ),
    error = function(e) die(paste0("glmer(null pairwise) failed: ", conditionMessage(e)))
  )

  s <- summary(m_full)
  cf <- s$coefficients
  coef_name <- "condition_bin"

  if (!(coef_name %in% rownames(cf))) {
    die(paste0("coefficient ", coef_name, " not found in pairwise model"))
  }

  beta <- cf[coef_name, "Estimate"]
  se <- cf[coef_name, "Std. Error"]
  z <- cf[coef_name, "z value"]
  wald_p2 <- cf[coef_name, "Pr(>|z|)"]

  lrt <- anova(m_null, m_full, test = "Chisq")
  lrt_p <- if ("Pr(>Chisq)" %in% colnames(lrt)) lrt[2, "Pr(>Chisq)"] else NA_real_

  or_hat <- exp(beta)
  or_lo <- exp(beta - 1.96 * se)
  or_hi <- exp(beta + 1.96 * se)

  conv_messages <- unlist(s$optinfo$conv$lme4$messages)
  conv_full <- isTRUE(length(conv_messages) == 0L)
  singular_full <- isTRUE(isSingular(m_full, tol = 1e-4))
  n_cycle <- length(levels(dsub$cycle))

  emit_row(
    "pairwise",
    "lme4_glmer_cycle_RE",
    reference_mode,
    comparison_mode,
    paste(mode_levels, collapse = ";"),
    2,
    nrow(dsub),
    conv_full,
    singular_full,
    beta,
    se,
    z,
    wald_p2,
    lrt_p,
    or_hat,
    or_lo,
    or_hi,
    n_cycle,
    ""
  )
  quit(status = 0)
}

if (analysis_kind == "omnibus") {
  if (length(args) < 4) {
    die("omnibus analysis requires at least 2 modes")
  }

  mode_levels <- args[3:length(args)]
  dsub <- df[df$mode %in% mode_levels, , drop = FALSE]
  dsub$mode <- factor(dsub$mode, levels = mode_levels)

  cat(
    sprintf(
      "[glmm] omnibus rows after mode filter (%s): %d\n",
      paste(mode_levels, collapse = ", "),
      nrow(dsub)
    ),
    file = stderr()
  )

  if (nrow(dsub) == 0) {
    emit_row(
      "omnibus",
      "lme4_glmer_cycle_RE",
      "",
      "",
      paste(mode_levels, collapse = ";"),
      length(mode_levels),
      0,
      FALSE,
      NA,
      NA,
      NA,
      NA,
      NA,
      NA,
      NA,
      NA,
      NA,
      0,
      "no_rows_after_mode_filter"
    )
    quit(status = 0)
  }

  if (length(unique(dsub$mode)) < 2) {
    emit_row(
      "omnibus",
      "lme4_glmer_cycle_RE",
      "",
      "",
      paste(mode_levels, collapse = ";"),
      length(mode_levels),
      nrow(dsub),
      FALSE,
      NA,
      NA,
      NA,
      NA,
      NA,
      NA,
      NA,
      NA,
      NA,
      length(levels(dsub$cycle)),
      "only_one_mode_present_after_filter"
    )
    quit(status = 0)
  }

  m_full <- tryCatch(
    glmer(
      succ ~ mode + (1 | cycle),
      data = dsub,
      family = binomial(link = "logit"),
      control = ctrl
    ),
    error = function(e) die(paste0("glmer(full omnibus) failed: ", conditionMessage(e)))
  )

  m_null <- tryCatch(
    glmer(
      succ ~ 1 + (1 | cycle),
      data = dsub,
      family = binomial(link = "logit"),
      control = ctrl
    ),
    error = function(e) die(paste0("glmer(null omnibus) failed: ", conditionMessage(e)))
  )

  s <- summary(m_full)
  conv_messages <- unlist(s$optinfo$conv$lme4$messages)
  conv_full <- isTRUE(length(conv_messages) == 0L)
  singular_full <- isTRUE(isSingular(m_full, tol = 1e-4))
  n_cycle <- length(levels(dsub$cycle))

  lrt <- anova(m_null, m_full, test = "Chisq")
  lrt_p <- if ("Pr(>Chisq)" %in% colnames(lrt)) lrt[2, "Pr(>Chisq)"] else NA_real_

  emit_row(
    "omnibus",
    "lme4_glmer_cycle_RE",
    "",
    "",
    paste(mode_levels, collapse = ";"),
    length(mode_levels),
    nrow(dsub),
    conv_full,
    singular_full,
    NA,
    NA,
    NA,
    NA,
    lrt_p,
    NA,
    NA,
    NA,
    n_cycle,
    ""
  )
  quit(status = 0)
}

die(paste0("unknown analysis kind: ", analysis_kind))