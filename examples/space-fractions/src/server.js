'use strict';

const { createApp } = require('./app');

// @req NFR-1
function start(port) {
  const app = createApp();
  const listenPort = port ?? process.env.PORT ?? 3000;

  return new Promise((resolve, reject) => {
    const server = app.listen(listenPort, (err) => {
      if (err) {
        reject(err);
        return;
      }
      resolve({ server, port: server.address().port });
    });
  });
}

if (require.main === module) {
  const port = process.env.PORT ? Number(process.env.PORT) : undefined;
  start(port).then(({ server, port: bound }) => {
    // eslint-disable-next-line no-console
    console.log(`Space Fractions listening on port ${bound}`);
  }).catch((err) => {
    // eslint-disable-next-line no-console
    console.error(err);
    process.exitCode = 1;
  });
}

module.exports = { start };
