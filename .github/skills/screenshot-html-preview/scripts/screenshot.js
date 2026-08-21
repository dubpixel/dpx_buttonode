/**
 * screenshot.js — dpx-buttonode-ui Playwright screenshot loop
 *
 * Paste this entire block into run_playwright_code.
 * Requires: html/ preview files already exist and have min-height:100vh removed.
 * Output:   overwrites images/001–006 in place.
 */
const BASE    = 'file:///Users/yourmom/Library/CloudStorage/GoogleDrive-i@dubpixel.tv/My%20Drive/_.DUBPIXEL/_...CODE/dpx_buttonode/html/';
const IMGDIR  = '/Users/yourmom/Library/CloudStorage/GoogleDrive-i@dubpixel.tv/My Drive/_.DUBPIXEL/_...CODE/dpx_buttonode/images/';
const WIDTH   = 920;

const TABS = [
  { file: 'dpx-buttonode-ui-preview.html',  out: '001_status.jpe'  },
  { file: 'dpx-buttonode-ui-hostname.html', out: '002_hostname.jpe' },
  { file: 'dpx-buttonode-ui-network.html',  out: '003_network.jpe'  },
  { file: 'dpx-buttonode-ui-devices.html',  out: '004_devices.jpe'  },
  { file: 'dpx-buttonode-ui-nodes.html',    out: '005_nodes.jpe'    },
  { file: 'dpx-buttonode-ui-mode.html',     out: '006_mode.jpe'     },
];

const saved = [];
for (const t of TABS) {
  // Step 1: tiny viewport → forces content to overflow → real scrollHeight
  await page.setViewportSize({ width: WIDTH, height: 200 });
  await page.goto(BASE + t.file);
  await page.waitForLoadState('networkidle');
  const h = await page.evaluate(() => document.documentElement.scrollHeight);

  // Step 2: reload at exact height → layout fully settled at final size
  await page.setViewportSize({ width: WIDTH, height: h });
  await page.reload();
  await page.waitForLoadState('networkidle');

  // Step 3: clip to exact content — no blank bottom, no blank right
  await page.screenshot({
    path: IMGDIR + t.out,
    fullPage: true,
    clip: { x: 0, y: 0, width: WIDTH, height: h }
  });
  saved.push({ out: t.out, cssW: WIDTH, cssH: h });
}
return saved;
