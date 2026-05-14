#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)

if (length(args) != 2) {
  cat("Usage: Rscript rq3_glmm_lme4.R <input_csv> <outdir>\n", file = stderr())
  quit(status = 2)
}

suppressPackageStartupMessages({
  library(lme4)
})

input_csv <- args[1]
outdir <- args[2]
dir.create(outdir, recursive = TRUE, showWarnings = FALSE)

obsolete_outputs <- c(
  "eval_rq3_cycle_summary.csv",
  "eval_rq3_importance.csv",
  "eval_rq3_cycle_improvement.csv",
  "eval_rq3_cycle_improvement_by_cycle.csv",
  "eval_rq3_cycle_improvement_importance.csv",
  "eval_rq3_configuration_slopes.csv",
  "eval_rq3_configuration_interactions.csv",
  "eval_scc_marginal_effects.csv",
  "eval_rq3_regression.csv",
  "eval_rq3_predictor_scaling.csv"
)
unlink(file.path(outdir, obsolete_outputs), force = TRUE)

die <- function(msg) {
  cat(paste0("ERROR: ", msg, "\n"), file = stderr())
  quit(status = 2)
}

fmt_ci <- function(lo, hi, digits = 3) {
  if (is.na(lo) || is.na(hi)) return(NA_character_)
  paste0(round(lo, digits), "--", round(hi, digits))
}

or_ci <- function(beta, se) {
  c(
    or = exp(beta),
    lo = exp(beta - 1.96 * se),
    hi = exp(beta + 1.96 * se)
  )
}

fit_glmm_or_null <- function(formula, data) {
  tryCatch(
    glmer(
      formula,
      data = data,
      family = binomial(link = "logit"),
      control = glmerControl(
        optimizer = "bobyqa",
        optCtrl = list(maxfun = 2e5)
      )
    ),
    error = function(e) {
      cat(paste0("[rq3] GLMM failed: ", conditionMessage(e), "\n"), file = stderr())
      NULL
    }
  )
}

transform_predictor <- function(x, transformation) {
  x <- as.numeric(x)

  if (transformation == "none") {
    return(x)
  }

  if (transformation == "log1p") {
    if (any(x < 0, na.rm = TRUE)) {
      die("log1p transformation received negative values")
    }
    return(log1p(x))
  }

  die(paste0("Unknown transformation: ", transformation))
}

empty_cycle_difficulty <- function() {
  data.frame(
    Pooled_success_rate_bin = c(
      "0%",
      ">0--10%",
      ">10--25%",
      ">25--50%",
      ">50--75%",
      ">75--<100%",
      "100%"
    ),
    Cycles = NA_integer_,
    Baseline_success_pct = NA_real_,
    Selected_success_pct = NA_real_,
    stringsAsFactors = FALSE
  )
}

empty_single_factor_models <- function() {
  data.frame(
    Structural_dimension = c(
      "Cycle size",
      "Cycle centrality",
      "Enclosing SCC size",
      "Repository size",
      "Cycle external connectivity"
    ),
    Coefficient = NA_real_,
    Odds_ratio = NA_real_,
    CI_95_odds_ratio = NA_character_,
    stringsAsFactors = FALSE
  )
}

write_empty_outputs <- function() {
  write.csv(
    empty_cycle_difficulty(),
    file.path(outdir, "eval_rq3_cycle_difficulty.csv"),
    row.names = FALSE
  )

  write.csv(
    empty_single_factor_models(),
    file.path(outdir, "eval_rq3_single_factor_models.csv"),
    row.names = FALSE
  )
}

success_pct <- function(successes, trials) {
  if (is.na(trials) || trials == 0) return(NA_real_)
  100.0 * successes / trials
}

difficulty_bin <- function(pooled_success_pct) {
  if (is.na(pooled_success_pct)) return(NA_character_)

  if (pooled_success_pct == 0) return("0%")
  if (pooled_success_pct <= 10) return(">0--10%")
  if (pooled_success_pct <= 25) return(">10--25%")
  if (pooled_success_pct <= 50) return(">25--50%")
  if (pooled_success_pct <= 75) return(">50--75%")
  if (pooled_success_pct < 100) return(">75--<100%")
  if (pooled_success_pct == 100) return("100%")

  return(NA_character_)
}

cycle_difficulty_row <- function(cycle_pair, label) {
  sub <- cycle_pair[cycle_pair$Pooled_success_rate_bin == label, , drop = FALSE]

  if (nrow(sub) == 0) {
    return(data.frame(
      Pooled_success_rate_bin = label,
      Cycles = 0L,
      Baseline_success_pct = NA_real_,
      Selected_success_pct = NA_real_,
      stringsAsFactors = FALSE
    ))
  }

  baseline_successes <- sum(sub$successes_baseline, na.rm = TRUE)
  baseline_trials <- sum(sub$trials_baseline, na.rm = TRUE)
  selected_successes <- sum(sub$successes_selected, na.rm = TRUE)
  selected_trials <- sum(sub$trials_selected, na.rm = TRUE)

  data.frame(
    Pooled_success_rate_bin = label,
    Cycles = nrow(sub),
    Baseline_success_pct = round(success_pct(baseline_successes, baseline_trials), 1),
    Selected_success_pct = round(success_pct(selected_successes, selected_trials), 1),
    stringsAsFactors = FALSE
  )
}

extract_single_factor_row <- function(model, predictor_col, label) {
  if (is.null(model)) {
    return(data.frame(
      Structural_dimension = label,
      Coefficient = NA_real_,
      Odds_ratio = NA_real_,
      CI_95_odds_ratio = NA_character_,
      stringsAsFactors = FALSE
    ))
  }

  cf <- summary(model)$coefficients

  if (!(predictor_col %in% rownames(cf))) {
    return(data.frame(
      Structural_dimension = label,
      Coefficient = NA_real_,
      Odds_ratio = NA_real_,
      CI_95_odds_ratio = NA_character_,
      stringsAsFactors = FALSE
    ))
  }

  beta <- cf[predictor_col, "Estimate"]
  se <- cf[predictor_col, "Std. Error"]
  ors <- or_ci(beta, se)

  data.frame(
    Structural_dimension = label,
    Coefficient = round(beta, 3),
    Odds_ratio = round(ors["or"], 3),
    CI_95_odds_ratio = fmt_ci(ors["lo"], ors["hi"]),
    stringsAsFactors = FALSE
  )
}

df <- read.csv(input_csv, stringsAsFactors = FALSE)

required <- c(
  "repo",
  "cycle_id",
  "mode_id",
  "success",
  "cycle_size",
  "cycle_centrality",
  "baseline_scc_size",
  "repo_dependency_graph_size",
  "cycle_external_edges"
)

missing <- setdiff(required, names(df))
if (length(missing) > 0) {
  die(paste0("missing required columns: ", paste(missing, collapse = ", ")))
}

df$success <- as.integer(df$success != 0)
df$cycle <- factor(paste(df$repo, df$cycle_id, sep = "::"))

modes <- unique(df$mode_id)

if (!("no_explain" %in% modes)) {
  die("expected one mode_id to be 'no_explain'")
}

non_baseline <- setdiff(modes, "no_explain")

if (length(non_baseline) != 1) {
  write_empty_outputs()
  cat(
    "[rq3] skipped RQ3 model tables because this analysis does not have exactly one baseline and one selected mode.\n",
    file = stderr()
  )
  quit(status = 0)
}

selected_mode <- non_baseline[1]
df$selected_system <- as.integer(df$mode_id == selected_mode)

predictor_specs <- list(
  cycle_size_z = list(
    label = "Cycle size",
    raw_col = "cycle_size",
    transformation = "none"
  ),
  cycle_centrality_z = list(
    label = "Cycle centrality",
    raw_col = "cycle_centrality",
    transformation = "log1p"
  ),
  baseline_scc_size_z = list(
    label = "Enclosing SCC size",
    raw_col = "baseline_scc_size",
    transformation = "log1p"
  ),
  repo_dependency_graph_size_z = list(
    label = "Repository size",
    raw_col = "repo_dependency_graph_size",
    transformation = "log1p"
  ),
  cycle_external_edges_z = list(
    label = "Cycle external connectivity",
    raw_col = "cycle_external_edges",
    transformation = "log1p"
  )
)

for (z_col in names(predictor_specs)) {
  spec <- predictor_specs[[z_col]]
  x <- transform_predictor(df[[spec$raw_col]], spec$transformation)
  mu <- mean(x, na.rm = TRUE)
  sig <- sd(x, na.rm = TRUE)

  if (is.na(sig) || sig == 0) {
    df[[z_col]] <- NA_real_
  } else {
    df[[z_col]] <- (x - mu) / sig
  }
}

base_model_cols <- c(
  "repo",
  "cycle_id",
  "cycle",
  "mode_id",
  "selected_system",
  "success"
)

difficulty_cols <- c(base_model_cols, names(predictor_specs))

difficulty_df <- df[
  complete.cases(df[, difficulty_cols]),
  difficulty_cols,
  drop = FALSE
]

cat(sprintf("[rq3] run-level rows after complete-case filtering: %d\n", nrow(difficulty_df)), file = stderr())

if (nrow(difficulty_df) == 0) {
  die("no rows remain after complete-case filtering")
}

cycle_mode_all <- aggregate(
  success ~ repo + cycle_id + cycle + mode_id + selected_system +
    cycle_size_z + cycle_centrality_z + baseline_scc_size_z +
    repo_dependency_graph_size_z + cycle_external_edges_z,
  data = difficulty_df,
  FUN = function(x) c(successes = sum(x), trials = length(x))
)

cycle_mode_all$successes <- cycle_mode_all$success[, "successes"]
cycle_mode_all$trials <- cycle_mode_all$success[, "trials"]
cycle_mode_all$success <- NULL
cycle_mode_all$success_rate <- cycle_mode_all$successes / cycle_mode_all$trials

cat(sprintf("[rq3] cycle-configuration rows: %d\n", nrow(cycle_mode_all)), file = stderr())
cat(sprintf("[rq3] cycles represented: %d\n", length(unique(cycle_mode_all$cycle))), file = stderr())

baseline_cycle <- cycle_mode_all[cycle_mode_all$mode_id == "no_explain", , drop = FALSE]
selected_cycle <- cycle_mode_all[cycle_mode_all$mode_id == selected_mode, , drop = FALSE]

keep <- c(
  "repo",
  "cycle_id",
  "successes",
  "trials",
  "success_rate"
)

cycle_pair <- merge(
  baseline_cycle[, keep, drop = FALSE],
  selected_cycle[, keep, drop = FALSE],
  by = c("repo", "cycle_id"),
  suffixes = c("_baseline", "_selected")
)

cycle_pair$pooled_success_pct <- (
  100.0 *
    (cycle_pair$successes_baseline + cycle_pair$successes_selected) /
    (cycle_pair$trials_baseline + cycle_pair$trials_selected)
)

cycle_pair$Pooled_success_rate_bin <- vapply(
  cycle_pair$pooled_success_pct,
  difficulty_bin,
  FUN.VALUE = character(1)
)

difficulty_levels <- c(
  "0%",
  ">0--10%",
  ">10--25%",
  ">25--50%",
  ">50--75%",
  ">75--<100%",
  "100%"
)

cycle_difficulty <- do.call(
  rbind,
  lapply(difficulty_levels, function(label) {
    cycle_difficulty_row(cycle_pair, label)
  })
)

write.csv(
  cycle_difficulty,
  file.path(outdir, "eval_rq3_cycle_difficulty.csv"),
  row.names = FALSE
)

single_factor_rows <- list()

for (z_col in names(predictor_specs)) {
  spec <- predictor_specs[[z_col]]
  model_cols <- c(base_model_cols, z_col)

  model_df <- df[
    complete.cases(df[, model_cols]),
    model_cols,
    drop = FALSE
  ]

  if (nrow(model_df) == 0) {
    cat(
      sprintf("[rq3] skipped %s because no complete rows remain\n", spec$label),
      file = stderr()
    )

    single_factor_rows[[length(single_factor_rows) + 1]] <- data.frame(
      Structural_dimension = spec$label,
      Coefficient = NA_real_,
      Odds_ratio = NA_real_,
      CI_95_odds_ratio = NA_character_,
      stringsAsFactors = FALSE
    )

    next
  }

  aggregate_formula <- as.formula(
    paste(
      "success ~ repo + cycle_id + cycle + mode_id + selected_system +",
      z_col
    )
  )

  cycle_mode <- aggregate(
    aggregate_formula,
    data = model_df,
    FUN = function(x) c(successes = sum(x), trials = length(x))
  )

  cycle_mode$successes <- cycle_mode$success[, "successes"]
  cycle_mode$trials <- cycle_mode$success[, "trials"]
  cycle_mode$failures <- cycle_mode$trials - cycle_mode$successes
  cycle_mode$success <- NULL

  model_formula <- as.formula(
    paste(
      "cbind(successes, failures) ~ selected_system +",
      z_col,
      "+ (1 | cycle)"
    )
  )

  model <- fit_glmm_or_null(model_formula, cycle_mode)

  cat(
    sprintf(
      "[rq3] single-factor model %-32s rows=%d cycles=%d\n",
      spec$label,
      nrow(cycle_mode),
      length(unique(cycle_mode$cycle))
    ),
    file = stderr()
  )

  single_factor_rows[[length(single_factor_rows) + 1]] <- extract_single_factor_row(
    model = model,
    predictor_col = z_col,
    label = spec$label
  )
}

write.csv(
  do.call(rbind, single_factor_rows),
  file.path(outdir, "eval_rq3_single_factor_models.csv"),
  row.names = FALSE
)

cat("[rq3] wrote eval_rq3_cycle_difficulty.csv\n", file = stderr())
cat("[rq3] wrote eval_rq3_single_factor_models.csv\n", file = stderr())