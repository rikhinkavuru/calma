# deterministic synthetic strategy: momentum on a sine-driven price series, base R only
n <- 300
i <- 0:(n-1)
price <- 100 * cumprod(1 + 0.0005*sin(i/8) + 0.0002*((i %% 6)-2.5)/2.5)
ret <- c(0, diff(price)/head(price, -1))
fast <- stats::filter(price, rep(1/10,10), sides=1)
slow <- stats::filter(price, rep(1/30,30), sides=1)
pos <- ifelse(!is.na(fast) & !is.na(slow) & fast > slow, 1, 0)
pos <- c(0, head(pos, -1))                  # shift to avoid lookahead
daily_return <- pos * ret
dir.create("runs", showWarnings=FALSE)
out <- data.frame(t=i, daily_return=daily_return)
write.csv(out, "runs/returns.csv", row.names=FALSE)
total <- prod(1 + daily_return) - 1
cat(sprintf("R strategy total_return = %.6f (R %s)\n", total, getRversion()))
