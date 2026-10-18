// Sleeps until an ISO time, then prints it. Used to ping at the next step of the live UI run.
const t = Date.parse(process.argv[2]);
while (Date.now() < t) await new Promise((r) => setTimeout(r, 15000));
console.log("TIME REACHED", new Date().toISOString());
