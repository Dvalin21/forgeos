// forge-terminal.js - Terminal component for Docker containers
class ForgeTerminal extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this.terminal = null;
    this.socket = null;
    this.containerName = null;
  }
  
  connectedCallback() {
    this.containerName = this.getAttribute('container') || 'unknown';
    this.render();
    this.initTerminal();
  }
  
  render() {
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          width: 100%;
          height: 100%;
          background: #0a1929;
          border-radius: var(--radius-md);
          overflow: hidden;
          font-family: 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
        }
        
        .terminal-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: var(--space-md) var(--space-lg);
          background: linear-gradient(135deg, rgba(0,180,216,0.1), rgba(0,180,216,0.05));
          border-bottom: 1px solid var(--border);
        }
        
        .terminal-title {
          color: var(--accent-primary);
          font-size: 13px;
          font-weight: 600;
          display: flex;
          align-items: center;
          gap: var(--space-sm);
        }
        
        .terminal-controls {
          display: flex;
          gap: var(--space-sm);
        }
        
        .control-btn {
          padding: var(--space-xs) var(--space-sm);
          background: rgba(255,255,255,0.05);
          border: 1px solid rgba(255,255,255,0.1);
          border-radius: var(--radius-sm);
          color: var(--text-secondary);
          cursor: pointer;
          font-size: 12px;
          transition: var(--transition);
        }
        
        .control-btn:hover {
          background: rgba(0,180,216,0.15);
          border-color: var(--accent-primary);
          color: var(--accent-primary);
        }
        
        .terminal-body {
          padding: var(--space-md);
          height: calc(100% - 48px);
          overflow-y: auto;
          font-size: 14px;
          line-height: 1.6;
          color: #00ff00;
        }
        
        .terminal-line {
          margin-bottom: 4px;
          white-space: pre-wrap;
          word-break: break-all;
        }
        
        .prompt {
          color: var(--accent-primary);
          font-weight: 600;
        }
        
        .cursor {
          display: inline-block;
          width: 8px;
          height: 16px;
          background: #00ff00;
          animation: blink 1s infinite;
          vertical-align: middle;
          margin-left: 2px;
        }
        
        @keyframes blink {
          0%, 50% { opacity: 1; }
          51%, 100% { opacity: 0; }
        }
        
        .terminal-input {
          display: flex;
          align-items: center;
          margin-top: var(--space-sm);
        }
        
        .terminal-input input {
          flex: 1;
          background: transparent;
          border: none;
          color: #00ff00;
          font-family: inherit;
          font-size: inherit;
          outline: none;
          caret-color: #00ff00;
        }
        
        .status-bar {
          padding: var(--space-sm) var(--space-md);
          background: rgba(0,0,0,0.3);
          border-top: 1px solid var(--border);
          font-size: 11px;
          color: var(--text-muted);
          display: flex;
          justify-content: space-between;
        }
      </style>
      
      <div class="terminal-header">
        <div class="terminal-title">
          <span>🐳</span>
          <span>Terminal: ${this.containerName}</span>
        </div>
        <div class="terminal-controls">
          <button class="control-btn" id="btn-clear">Clear</button>
          <button class="control-btn" id="btn-copy">Copy</button>
          <button class="control-btn" id="btn-disconnect">Disconnect</button>
        </div>
      </div>
      
      <div class="terminal-body" id="terminal-output">
        <div class="terminal-line">
          <span class="prompt">root@${this.containerName}:/#</span> <span id="welcome-text">Connecting to container...</span>
        </div>
      </div>
      
      <div class="status-bar">
        <span id="status-text">Disconnected</span>
        <span>Press Ctrl+C to interrupt</span>
      </div>
    `;
  }
  
  initTerminal() {
    // Simulate terminal connection
    setTimeout(() => {
      this.addLine('Connected to container: ' + this.containerName);
      this.addLine('Type "help" for available commands.');
      this.addPrompt();
    }, 500);
    
    // Setup control buttons
    this.shadowRoot.querySelector('#btn-clear').addEventListener('click', () => {
      this.clearTerminal();
    });
    
    this.shadowRoot.querySelector('#btn-disconnect').addEventListener('click', () => {
      this.disconnect();
    });
    
    this.shadowRoot.querySelector('#btn-copy').addEventListener('click', () => {
      this.copyOutput();
    });
    
    // Simulate WebSocket connection (in production, connect to Docker API)
    this.connectWebSocket();
  }
  
  addLine(text) {
    const output = this.shadowRoot.querySelector('#terminal-output');
    const line = document.createElement('div');
    line.className = 'terminal-line';
    line.textContent = text;
    output.appendChild(line);
    output.scrollTop = output.scrollHeight;
  }
  
  addPrompt() {
    const output = this.shadowRoot.querySelector('#terminal-output');
    const promptLine = document.createElement('div');
    promptLine.className = 'terminal-line terminal-input';
    promptLine.innerHTML = `
      <span class="prompt">root@${this.containerName}:/#</span>
      <input type="text" id="cmd-input" autofocus />
    `;
    output.appendChild(promptLine);
    
    const input = promptLine.querySelector('#cmd-input');
    input.focus();
    
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        const cmd = input.value;
        if (cmd.trim()) {
          this.executeCommand(cmd);
        }
        input.value = '';
      }
    });
    
    output.scrollTop = output.scrollHeight;
  }
  
  executeCommand(cmd) {
    this.addLine(cmd);
    
    // Simulate command execution
    setTimeout(() => {
      switch(cmd.toLowerCase().trim()) {
        case 'help':
          this.addLine('Available commands: help, ls, pwd, cd, echo, clear, exit');
          break;
        case 'ls':
          this.addLine('bin/  boot/  dev/  etc/  home/  lib/  media/  mnt/  opt/  proc/  root/  run/  sbin/  srv/  sys/  tmp/  usr/  var/');
          break;
        case 'pwd':
          this.addLine('/root');
          break;
        case 'clear':
          this.clearTerminal();
          break;
        case 'exit':
          this.addLine('Use Ctrl+C to interrupt or type "exit" to close terminal.');
          break;
        default:
          this.addLine(`bash: ${cmd}: command not found`);
      }
      this.addPrompt();
    }, 200);
  }
  
  clearTerminal() {
    const output = this.shadowRoot.querySelector('#terminal-output');
    output.innerHTML = '';
    this.addLine('Terminal cleared.');
    this.addPrompt();
  }
  
  disconnect() {
    if (this.socket) {
      this.socket.close();
    }
    this.addLine('Disconnected from container.');
    const statusText = this.shadowRoot.querySelector('#status-text');
    if (statusText) statusText.textContent = 'Disconnected';
  }
  
  copyOutput() {
    const output = this.shadowRoot.querySelector('#terminal-output');
    const text = output.innerText;
    navigator.clipboard.writeText(text).then(() => {
      const btn = this.shadowRoot.querySelector('#btn-copy');
      const originalText = btn.textContent;
      btn.textContent = 'Copied!';
      setTimeout(() => { btn.textContent = originalText; }, 2000);
    });
  }
  
  connectWebSocket() {
    // In production, this would connect to a WebSocket endpoint
    // that proxies Docker exec commands
    const statusText = this.shadowRoot.querySelector('#status-text');
    if (statusText) statusText.textContent = 'Connected (simulated)';
    
    // Simulate receiving data
    console.log(`Terminal for ${this.containerName} initialized (WebSocket simulation mode)`);
  }
}

customElements.define('forge-terminal', ForgeTerminal);
