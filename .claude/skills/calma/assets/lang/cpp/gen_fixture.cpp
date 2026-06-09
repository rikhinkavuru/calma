// Calma cross-language fixture (C++). Honest computation; the CONTRACT overstates the claim (fraud).
#include <cstdio>
#include <cmath>
#include <sys/stat.h>
int main(){
  mkdir("runs", 0755);
  FILE* f = fopen("runs/returns.csv","w");
  fprintf(f, "daily_return\n");
  double acc = 1.0;
  for (int i=0;i<252;i++){ double x = 0.0005 + 0.03*std::sin(i*0.2); fprintf(f,"%.17g\n",x); acc*=(1.0+x); }
  fclose(f);
  printf("total_return=%.17g\n", acc-1.0);
  return 0;
}
