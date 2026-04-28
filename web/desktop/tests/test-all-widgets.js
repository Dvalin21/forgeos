// web/desktop/tests/test-all-widgets.js
const widgets = ['widget-storage', 'widget-network', 'widget-alerts'];

widgets.forEach(widgetName => {
  try {
    const widget = document.createElement(widgetName);
    document.body.appendChild(widget);
    console.log(`PASS: ${widgetName} created`);
  } catch (e) {
    console.error(`FAIL: Could not create ${widgetName}: ${e.message}`);
  }
});
