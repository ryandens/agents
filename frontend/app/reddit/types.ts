export interface RedditDay {
  day: string;
  has_history: boolean;
  visits: number;
  raw_visits: number;
  unique_posts: number;
}
export interface SubredditCount {
  subreddit: string | null;
  visits: number;
  raw_visits: number;
}
export interface RedditReport {
  days: RedditDay[];
  subreddits: SubredditCount[];
}
export interface RedditVisit {
  timestamp: string;
  url: string;
  title: string;
  subreddit: string | null;
}
export interface RedditVisits {
  visits: RedditVisit[];
  total: number;
  limit: number;
  offset: number;
}
export type Metric = "visits" | "raw_visits";
export const NO_SUBREDDIT = "__none__";
export const communityName = (name: string | null) =>
  name ? `r/${name}` : "Other Reddit pages";
