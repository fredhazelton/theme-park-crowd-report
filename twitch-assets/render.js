const puppeteer = require('puppeteer');
const path = require('path');

const screens = [
  { name: 'banner', width: 1200, height: 480 },
  { name: 'starting-soon', width: 1920, height: 1080 },
  { name: 'brb', width: 1920, height: 1080 },
  { name: 'stream-ended', width: 1920, height: 1080 },
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
    
    const htmlPath = path.join(__dirname, `${screen.name}.html`);
    await page.goto(`file://${htmlPath}`, { waitUntil: 'networkidle0' });
    
    await page.screenshot({
      path: path.join(__dirname, `${screen.name}.png`),
      type: 'png'
    });
    
    await page.close();
    console.log(`  ✓ ${screen.name}.png`);
  }
  
  await browser.close();
  console.log('\nDone! All assets rendered.');
})();
