// Records the demo takes from the live app (through `sprite proxy -s airlock-ctrl 18080:8080`).
// Usage: node record.mjs [A B C ...]      (default: all takes, in order)
// Output: takes/<take>.webm + takes/<take>.json (marks: seconds from the start of the video)
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const BASE = process.env.AIRLOCK_UI || "http://127.0.0.1:18080";
const ROOT = path.resolve(import.meta.dirname, "..");
const SAMPLES = path.join(ROOT, "samples");
const OUT = path.join(import.meta.dirname, "takes");
const password = fs.readFileSync(path.join(ROOT, ".env.ctrl"), "utf8").match(/AIRLOCK_PASSWORD=(\S+)/)[1];
fs.mkdirSync(OUT, { recursive: true });

// Recorded at 1536x864 and scaled 1.25x to 1920x1080 in Remotion: looks like browser zoom 125%.
// (Playwright's video ignores deviceScaleFactor, so the zoom happens in the edit.)
const VIEW = { width: 1536, height: 864 };
const SCALE = 1;
const FRAME = VIEW;

// A visible cursor (headless video has none) that eases to every click.
const CURSOR = `
  window.addEventListener('DOMContentLoaded', () => {
    const c = document.createElement('div');
    c.id = '__cursor';
    c.style.cssText = 'position:fixed;z-index:2147483647;left:0;top:0;width:22px;height:22px;pointer-events:none;' +
      'transform:translate(-3px,-2px);transition:transform .05s';
    c.innerHTML = '<svg viewBox="0 0 24 24" width="22" height="22"><path d="M3 2l7 19 2.6-7.6L20 11z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    document.body.appendChild(c);
    document.addEventListener('mousemove', e => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; }, true);
    document.addEventListener('mousedown', () => c.style.transform = 'translate(-3px,-2px) scale(.85)', true);
    document.addEventListener('mouseup', () => c.style.transform = 'translate(-3px,-2px)', true);
  });`;

const sleep = ms => new Promise(r => setTimeout(r, ms));

async function session(browser) {
  const ctx = await browser.newContext({ viewport: VIEW, deviceScaleFactor: SCALE });
  const page = await ctx.newPage();
  await page.goto(BASE + "/login");
  await page.fill('input[name="password"]', password);
  await Promise.all([page.waitForURL(BASE + "/"), page.click('button[type="submit"]')]);
  const state = await ctx.storageState();
  await ctx.close();
  return state;
}

async function take(browser, state, name, script) {
  const ctx = await browser.newContext({
    viewport: VIEW, deviceScaleFactor: SCALE, storageState: state,
    recordVideo: { dir: OUT, size: FRAME },
  });
  await ctx.addInitScript(CURSOR);
  const page = await ctx.newPage();
  const t0 = Date.now();
  const marks = {};
  const mark = k => { marks[k] = +((Date.now() - t0) / 1000).toFixed(2); console.log(`  ${name} ${k} @ ${marks[k]}s`); };
  let pos = { x: 760, y: 430 };
  const move = async (x, y) => { await page.mouse.move(x, y, { steps: 28 }); pos = { x, y }; await sleep(150); };
  const clickOn = async locator => {
    await locator.scrollIntoViewIfNeeded();
    const b = await locator.boundingBox();
    await move(b.x + b.width / 2, b.y + b.height / 2);
    await page.mouse.down(); await sleep(70); await page.mouse.up();
    await sleep(250);
  };
  const typeInto = async (locator, text, { clear = false } = {}) => {
    await clickOn(locator);
    if (clear) { await locator.press("Control+A"); await locator.press("Delete"); }
    await locator.pressSequentially(text, { delay: 55 });
  };
  const upload = async file => {
    const [chooser] = await Promise.all([page.waitForEvent("filechooser"), clickOn(page.locator("#upload"))]);
    await chooser.setFiles(path.join(SAMPLES, file));
  };
  const openDoc = name => clickOn(page.locator("#docs .doc", { hasText: name }).first());
  const waitText = (text, timeout = 120000) => page.getByText(text, { exact: false }).first().waitFor({ timeout });
  const openDetails = async summaryText => {
    const s = page.locator("summary", { hasText: summaryText }).first();
    await clickOn(s);
  };

  await page.goto(BASE + "/");
  await page.mouse.move(pos.x, pos.y);
  await waitText("DOCUMENTS");
  await sleep(1500);
  mark("ready");
  try {
    await script({ page, mark, sleep, clickOn, typeInto, upload, openDoc, waitText, openDetails, move });
  } finally {
    mark("end");
    const video = page.video();
    await ctx.close();
    const src = await video.path();
    fs.renameSync(src, path.join(OUT, `${name}.webm`));
    fs.writeFileSync(path.join(OUT, `${name}.json`), JSON.stringify(marks, null, 1));
  }
}

const TAKES = {
  // 3: bill -> AUTO, the code that checks the sum, back to CLEAN
  A: async ({ page, mark, sleep, upload, waitText, openDetails }) => {
    await upload("electric-bill-oct.pdf"); mark("uploaded");
    await waitText("Chamber is reading", 30000); mark("reading");
    await waitText("Agent is working", 90000); mark("agent");
    await waitText("Filed on Box automatically", 120000); mark("filed");
    await page.locator("#chamber", { hasText: "CLEAN" }).waitFor({ timeout: 60000 }); mark("clean");
    await sleep(1200);
    await openDetails("code the model wrote"); mark("code");
    await sleep(3500);
  },
  // 4: invoice -> the agent's code finds the overcharge
  B: async ({ mark, sleep, upload, waitText, openDetails }) => {
    await upload("plumber-invoice.pdf"); mark("uploaded");
    await page.locator("#detail h2", { hasText: "plumber-invoice.pdf" }).waitFor({ timeout: 30000 });
    await page.locator("#detail", { hasText: "Needs your review" }).waitFor({ timeout: 150000 }); mark("review");
    await sleep(2500);
    await openDetails("code the model wrote"); mark("code");
    await sleep(4000);
  },
  // 5a: review the October paystub: change the issuer, write a note, approve
  C: async ({ page, mark, sleep, openDoc, typeInto, clickOn, waitText }) => {
    await openDoc("paystub-oct.pdf"); mark("open");
    await sleep(2500);
    await typeInto(page.locator('input[name="issuer"]'), "Acme Software (payroll)", { clear: true }); mark("issuer");
    await typeInto(page.locator('textarea[name="note"]'), "Acme paystubs: write the issuer as Acme Software (payroll)"); mark("note");
    await sleep(600);
    await clickOn(page.locator('button[name="approve"]')); mark("approve");
    await waitText("Approved by you, filed on Box", 90000); mark("filed");
    await sleep(3000);
  },
  // 5b: the November paystub comes in and uses the remembered correction
  D: async ({ page, mark, sleep, upload, waitText, clickOn }) => {
    await upload("paystub-nov.pdf"); mark("uploaded");
    await page.locator("#detail h2", { hasText: "paystub-nov.pdf" }).waitFor({ timeout: 30000 });
    await page.locator("#detail", { hasText: "Needs your review" }).waitFor({ timeout: 150000 }); mark("review");
    await sleep(2500);
    const hit = page.getByText("Pinecone match", { exact: false }).first();
    await hit.scrollIntoViewIfNeeded(); mark("memory");
    await sleep(4000);
  },
  // 6: the two hostile contracts (processed before recording)
  E: async ({ mark, sleep, openDoc }) => {
    await openDoc("vendor-contract.pdf"); mark("contract");
    await sleep(4500);
    await openDoc("service-agreement-v2.pdf"); mark("paraphrase");
    await sleep(4500);
  },
  // 7: red-team drill, live, until the chamber is clean again
  F: async ({ page, mark, sleep, clickOn, waitText }) => {
    await clickOn(page.locator("#redteam")); mark("drill");
    await page.locator("#chamber", { hasText: "DIRTY" }).waitFor({ timeout: 60000 }); mark("dirty");
    await waitText("Red alarm: quarantined", 120000); mark("red");
    await page.locator("#chamber", { hasText: "RESTORING" }).waitFor({ timeout: 60000 }).catch(() => {}); mark("restoring");
    await page.locator("#chamber", { hasText: "CLEAN" }).waitFor({ timeout: 90000 }); mark("clean");
    await sleep(3500);
  },
};

const which = process.argv.slice(2).length ? process.argv.slice(2) : Object.keys(TAKES);
const browser = await chromium.launch();
try {
  const state = await session(browser);
  for (const name of which) {
    console.log(`take ${name}`);
    await take(browser, state, name, TAKES[name]);
  }
} finally {
  await browser.close();
}
