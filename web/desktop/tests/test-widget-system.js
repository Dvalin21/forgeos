// web/desktop/tests/test-widget-system.js
// This test verifies the System Health widget can be created and loads data

async function testWidgetSystem() {
  // Create widget
  const widget = document.createElement('widget-system');
  document.body.appendChild(widget);
  
  // Wait for data to load (async)
  await new Promise(resolve => setTimeout(resolve, 1000));
  
  // Check if content updated from "Loading..."
  const content = widget.shadowRoot.querySelector('.content').textContent;
  if (content !== 'Loading...') {
    console.log('PASS: Widget loaded data');
  } else {
    console.error('FAIL: Widget still showing Loading...');
  }
}

testWidgetSystem();
