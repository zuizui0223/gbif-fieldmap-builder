#' Recommend top survey candidates with equal area quotas
#'
#' @param candidates A data.frame containing site identifiers and priority scores.
#' @param per_area Number of sites retained per survey area.
#' @param default_total Number retained when only one area is present.
#' @param area_col,score_col,id_col Column names.
#' @param extent Optional numeric vector ordered west, south, east, north.
#' @param latitude_col,longitude_col Coordinate column names used with extent.
#' @return A ranked data.frame.
#' @export
acsp_recommend <- function(candidates, per_area = 3L, default_total = 8L,
                           area_col = "survey_area_id",
                           score_col = "priority_score", id_col = "site_id",
                           extent = NULL, latitude_col = "latitude", longitude_col = "longitude") {
  stopifnot(is.data.frame(candidates), score_col %in% names(candidates), id_col %in% names(candidates))
  if (!is.null(extent)) {
    if (length(extent) != 4L || any(!is.finite(extent)) || extent[[1L]] >= extent[[3L]] || extent[[2L]] >= extent[[4L]]) {
      stop("extent must be finite west, south, east, north values with west < east and south < north")
    }
    stopifnot(latitude_col %in% names(candidates), longitude_col %in% names(candidates))
    inside <- candidates[[longitude_col]] >= extent[[1L]] & candidates[[longitude_col]] <= extent[[3L]] &
      candidates[[latitude_col]] >= extent[[2L]] & candidates[[latitude_col]] <= extent[[4L]]
    candidates <- candidates[!is.na(inside) & inside, , drop = FALSE]
  }
  candidates <- candidates[order(-candidates[[score_col]], candidates[[id_col]]), , drop = FALSE]
  if (area_col %in% names(candidates) && length(unique(candidates[[area_col]])) > 1L) {
    selected <- do.call(rbind, lapply(split(candidates, candidates[[area_col]]), utils::head, n = per_area))
    selected <- selected[order(selected[[area_col]], -selected[[score_col]]), , drop = FALSE]
  } else {
    selected <- utils::head(candidates, default_total)
  }
  rownames(selected) <- NULL
  selected$recommendation_rank <- seq_len(nrow(selected))
  selected
}
