\name{acsp_recommend}
\alias{acsp_recommend}
\title{Recommend Top Survey Candidates}
\usage{acsp_recommend(candidates, per_area = 3L, default_total = 8L,
  area_col = "survey_area_id", score_col = "priority_score", id_col = "site_id",
  extent = NULL, latitude_col = "latitude", longitude_col = "longitude")}
\arguments{
  \item{candidates}{A data frame of candidate sites.}
  \item{per_area}{Number retained per survey area.}
  \item{default_total}{Number retained when only one area is present.}
  \item{area_col, score_col, id_col}{Column names.}
  \item{extent}{Optional numeric vector ordered west, south, east, north.}
  \item{latitude_col, longitude_col}{Coordinate column names used with extent.}
}
\value{A ranked data frame.}
\description{Selects top-ranked candidates with equal quotas across multiple survey areas.}
