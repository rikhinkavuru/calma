# Calma cross-language fixture (Julia).
mkpath("runs")
r = [0.0005 + 0.03*sin(i*0.2) for i in 0:251]
open("runs/returns.csv","w") do io
    println(io, "daily_return"); for x in r; println(io, x); end
end
acc = prod(1.0 .+ r)
println("total_return=", acc-1.0)
