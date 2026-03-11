module.exports = {
  apps: [{
    name: 'playlist-generator-frontend',
    script: '.output/server/index.mjs',
    cwd: '/home/tom/projects/playlist-generator/frontend',
    env: {
      PORT: 3000,
      HOST: '0.0.0.0',
    },
  }],
};
