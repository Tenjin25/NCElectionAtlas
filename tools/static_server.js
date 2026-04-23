const http = require('http');
const fs = require('fs');
const path = require('path');
const { URL } = require('url');

function getArgValue(argv, name, fallback = null) {
  const idx = argv.indexOf(name);
  if (idx === -1) return fallback;
  const next = argv[idx + 1];
  if (!next || next.startsWith('--')) return fallback;
  return next;
}

const argv = process.argv.slice(2);
const port = Number(getArgValue(argv, '--port', '4173'));
const host = getArgValue(argv, '--host', '127.0.0.1');
const rootDir = process.cwd();

const mimeByExt = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.webp': 'image/webp',
  '.ico': 'image/x-icon',
  '.txt': 'text/plain; charset=utf-8',
  '.csv': 'text/csv; charset=utf-8'
};

function safeResolve(requestPath) {
  const cleaned = decodeURIComponent(String(requestPath || '').replace(/\0/g, ''));
  const withoutQuery = cleaned.split('?')[0].split('#')[0];
  const joined = path.join(rootDir, withoutQuery);
  const resolved = path.resolve(joined);
  const rootResolved = path.resolve(rootDir);
  if (!resolved.startsWith(rootResolved)) return null;
  return resolved;
}

const server = http.createServer((req, res) => {
  try {
    const url = new URL(req.url || '/', `http://${host}:${port}`);
    const pathname = url.pathname === '/' ? '/index.html' : url.pathname;
    let filePath = safeResolve(pathname);
    if (!filePath) {
      res.writeHead(400, { 'Content-Type': 'text/plain; charset=utf-8' });
      res.end('Bad request');
      return;
    }

    // If a directory is requested, serve its index.html if present.
    if (fs.existsSync(filePath) && fs.statSync(filePath).isDirectory()) {
      filePath = path.join(filePath, 'index.html');
    }

    fs.readFile(filePath, (err, data) => {
      if (err) {
        res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
        res.end('Not found');
        return;
      }
      const ext = path.extname(filePath).toLowerCase();
      const contentType = mimeByExt[ext] || 'application/octet-stream';
      res.writeHead(200, {
        'Content-Type': contentType,
        'Cache-Control': 'no-store'
      });
      res.end(data);
    });
  } catch (e) {
    res.writeHead(500, { 'Content-Type': 'text/plain; charset=utf-8' });
    res.end('Server error');
  }
});

server.listen(port, host, () => {
  // eslint-disable-next-line no-console
  console.log(`Static server listening on http://${host}:${port}`);
});

