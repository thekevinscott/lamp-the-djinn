import { defineConfig } from 'vitepress'

export default defineConfig({
  title: 'lamp-the-djinn',
  description: 'A sandbox for running any coding agent with full autonomy, without risking your system.',
  base: '/lamp-the-djinn/',
  cleanUrls: true,
  themeConfig: {
    nav: [
      { text: 'Getting Started', link: '/getting-started' },
      { text: 'Deep Dive', link: '/deep-dive' },
      { text: 'Troubleshooting', link: '/troubleshooting/' },
    ],
    sidebar: [
      { text: 'Getting Started', link: '/getting-started' },
      { text: 'Deep Dive', link: '/deep-dive' },
      {
        text: 'Troubleshooting',
        items: [
          { text: 'Overview', link: '/troubleshooting/' },
          { text: 'GPG signing', link: '/troubleshooting/gpg-signing' },
          { text: 'Mounting additional folders', link: '/troubleshooting/mounting-folders' },
        ],
      },
    ],
    socialLinks: [{ icon: 'github', link: 'https://github.com/thekevinbot/lamp-the-djinn' }],
    search: { provider: 'local' },
    outline: [2, 3],
  },
})
