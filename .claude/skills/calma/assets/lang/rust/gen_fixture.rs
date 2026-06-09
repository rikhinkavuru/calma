// Calma cross-language fixture (Rust).
use std::fs; use std::io::Write;
fn main(){
  fs::create_dir_all("runs").unwrap();
  let mut f = fs::File::create("runs/returns.csv").unwrap();
  writeln!(f, "daily_return").unwrap();
  let mut acc = 1.0f64;
  for i in 0..252 { let x = 0.0005 + 0.03*((i as f64)*0.2).sin(); writeln!(f, "{}", x).unwrap(); acc *= 1.0+x; }
  println!("total_return={}", acc-1.0);
}
