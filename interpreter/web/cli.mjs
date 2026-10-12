#!/usr/bin/env node
// Run a Malbolge program with the WebAssembly build:
//   node cli.mjs [-m classic|fast20] program.mb < input
import { readFileSync, writeSync } from "node:fs";
import { Fastbolge, HALTED, PAUSED } from "./fastbolge.mjs";

const args = process.argv.slice(2);
let mode = "classic";
if (args[0] === "-m") { mode = args[1]; args.splice(0, 2); }
const fb = await Fastbolge.instantiate(readFileSync(new URL("./fastbolge.wasm", import.meta.url)));
const err = fb.load(mode, readFileSync(args[0]));
if (err) { process.stderr.write(`fastbolge: ${err}\n`); process.exit(2); }
let input;
try { input = readFileSync(0); } catch { input = new Uint8Array(); }
fb.setInput(input);
let limit = 0, status;
do {
  limit += 50_000_000;
  status = fb.run(limit);
  const out = fb.takeOutput();
  if (out.length) writeSync(1, out);
} while (status === PAUSED);
if (status !== HALTED) { process.stderr.write(`fastbolge: ${fb.message()}\n`); process.exit(3); }
