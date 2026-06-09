// Calma cross-language fixture (Node.js).
const fs = require('fs');
fs.mkdirSync('runs', {recursive:true});
let lines = ['daily_return']; let acc = 1.0;
for (let i=0;i<252;i++){ const x = 0.0005 + 0.03*Math.sin(i*0.2); lines.push(String(x)); acc *= (1.0+x); }
fs.writeFileSync('runs/returns.csv', lines.join('\n')+'\n');
console.log('total_return='+(acc-1.0));
