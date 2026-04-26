/**
 * Load a Guitar Pro 3–8 .gp / .gpx / .gpif bundle and write a type-1 SMF .mid
 * (same as Songsterr's in-browser export path when their API fails).
 *
 * Usage: node gp7_to_midi.mjs <input.gp> <output.mid>
 * Run with cwd = this directory so node can resolve @coderline/alphatab.
 */
import fs from "node:fs";
import * as alphaTab from "@coderline/alphatab";

const inPath = process.argv[2];
const outPath = process.argv[3];
if (!inPath || !outPath) {
  console.error("Usage: node gp7_to_midi.mjs <input.gp> <output.mid>");
  process.exit(1);
}

const fileData = fs.readFileSync(inPath);
const settings = new alphaTab.Settings();
const score = alphaTab.importer.ScoreLoader.loadScoreFromBytes(
  new Uint8Array(fileData),
  settings
);
const midiFile = new alphaTab.midi.MidiFile();
const handler = new alphaTab.midi.AlphaSynthMidiFileHandler(midiFile, true);
const generator = new alphaTab.midi.MidiFileGenerator(score, settings, handler);
generator.generate();
const bytes = midiFile.toBinary();
fs.writeFileSync(outPath, Buffer.from(bytes));
