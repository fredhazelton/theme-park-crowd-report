const puppeteer = require('puppeteer');
const path = require('path');

const screens = [
  { name: 'banner-v3', width: 1200, height: 480 },
  { name: 'starting-soon-v3', width: 1920, height: 1080 },
  { name: 'brb-v3', width: 1920, height: 1080 },
  { name: 'stream-ended-v3', width: 1920, height: 1080 },
];

(async () => {
  const browser = await puppeteer.launch({
    headless: 'new',
    args: ['--no-sandbox', '--disable-setuid-sandbox']
  });
  
  for (const screen of screens) {
    console.log(`Rendering ${screen.name}...`);
    const page = await browser.newPage();
    await page.setViewport({ width: screen.width, height: screen.height });
    
    const htmlPath = path.resolve(__dirname, `${screen.name}.html`);
    await page.goto(`file://${htmlPath}`, { waitUntil: 'networkidle0' });
    
    // Wait for images to load
    await new Promise(r => setTimeout(r, 1500));
    
    await page.screenshot({
      path: path.resolve(__dirname, `${screen.name}.png`),
      type: 'png'
    });
    
    await page.close();
    console.log(`  ✓ ${screen.name}.png`);
  }
  
  await browser.close();
  console.log('\nDone! V3 assets rendered.');
})();
