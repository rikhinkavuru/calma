# Calma cross-language fixture (R). Emits the shared deterministic return series; prints total_return.
dir.create("runs", showWarnings=FALSE)
r <- sapply(0:251, function(i) 0.0005 + 0.03*sin(i*0.2))
con <- file("runs/returns.csv","w"); writeLines("daily_return", con)
for (x in r) writeLines(format(x, digits=17), con)
close(con)
cat(sprintf("total_return=%.17g\n", prod(1+r)-1))
