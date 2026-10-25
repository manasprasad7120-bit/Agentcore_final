import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import axios from "axios";
import dotenv from "dotenv";

dotenv.config();

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const KEY = process.env.AZURE_TRANSLATOR_KEY;
const ENDPOINT = process.env.AZURE_TRANSLATOR_ENDPOINT;
const REGION = process.env.AZURE_REGION;

const LOCALES_ROOT = path.join(__dirname, "locales");
const SOURCE_FILE = path.join(LOCALES_ROOT, "en-US", "translation.json");
const LANGUAGES_FILE = path.join(LOCALES_ROOT, "languages.json");

// Only translate keys whose en-US definitions appear at this line or later.
// Override via CLI arg: `node translate-all.js 1500`
const START_LINE = Number(process.argv[2]) || 1500;

// Matches a single-line "key": "value", entry. Both strings are
// JSON-encoded so JSON.parse handles escapes correctly.
const KEY_LINE_REGEX =
  /^\s*("(?:[^"\\]|\\.)*")\s*:\s*("(?:[^"\\]|\\.)*")\s*,?\s*$/;

function parseKeysAtOrAfter(filePath, startLine) {
  const text = fs.readFileSync(filePath, "utf-8");
  const lines = text.split(/\r?\n/);
  const entries = [];
  for (let i = 0; i < lines.length; i++) {
    const lineNo = i + 1;
    if (lineNo < startLine) continue;
    const match = lines[i].match(KEY_LINE_REGEX);
    if (!match) continue;
    try {
      const k = JSON.parse(match[1]);
      const v = JSON.parse(match[2]);
      entries.push([k, v]);
    } catch {
      // skip lines we can't parse
    }
  }
  return entries;
}

async function translateText(text, toLang) {
  const url = `${ENDPOINT}/translate?api-version=3.0&to=${toLang}`;
  const res = await axios.post(
    url,
    [{ Text: text }],
    {
      headers: {
        "Ocp-Apim-Subscription-Key": KEY,
        "Ocp-Apim-Subscription-Region": REGION,
        "Content-Type": "application/json",
      },
    },
  );
  return res.data[0].translations[0].text;
}

async function main() {
  if (!KEY || !ENDPOINT || !REGION) {
    console.error(
      "❌ Missing AZURE_TRANSLATOR_KEY / AZURE_TRANSLATOR_ENDPOINT / AZURE_REGION in env.",
    );
    process.exit(1);
  }

  const languages = JSON.parse(fs.readFileSync(LANGUAGES_FILE, "utf-8"));
  const newEntries = parseKeysAtOrAfter(SOURCE_FILE, START_LINE);

  if (newEntries.length === 0) {
    console.log(`No translatable keys found from line ${START_LINE} onwards.`);
    return;
  }
  console.log(
    `📖 Source: ${SOURCE_FILE}\n📍 Start line: ${START_LINE}\n🔑 Keys to process: ${newEntries.length}\n`,
  );

  for (const lang of languages) {
    if (lang.code === "en-US") continue; // never translate the source

    const langFolder = path.join(LOCALES_ROOT, lang.code);
    const outputPath = path.join(langFolder, "translation.json");

    if (!fs.existsSync(langFolder)) {
      fs.mkdirSync(langFolder, { recursive: true });
    }

    // Load existing file as-is so we preserve its order and contents.
    let existing = {};
    if (fs.existsSync(outputPath)) {
      try {
        existing = JSON.parse(fs.readFileSync(outputPath, "utf-8"));
      } catch (err) {
        console.warn(
          `⚠️  ${lang.code}: could not parse ${outputPath} (${err.message}). Skipping language to avoid data loss.`,
        );
        continue;
      }
    }

    let added = 0;
    let skipped = 0;
    for (const [k, v] of newEntries) {
      // Never overwrite an existing translation.
      if (Object.prototype.hasOwnProperty.call(existing, k)) {
        skipped += 1;
        continue;
      }
      try {
        const translated = await translateText(v, lang.code);
        existing[k] = translated;
        added += 1;
      } catch (err) {
        console.error(`  ❌  ${lang.code} :: ${k} — ${err.message}`);
      }
    }

    if (added > 0) {
      // V8 preserves object key insertion order, so existing keys stay in
      // their original positions and the new ones land at the end.
      fs.writeFileSync(
        outputPath,
        JSON.stringify(existing, null, 2) + "\n",
      );
      console.log(
        `✅ ${lang.code} (${lang.title}): +${added} new, ${skipped} already present`,
      );
    } else {
      console.log(
        `➖ ${lang.code} (${lang.title}): nothing to add (${skipped} already present)`,
      );
    }
  }

  console.log("\n🎉 Done.");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
