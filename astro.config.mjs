import { defineConfig } from 'astro/config';
import Unocss from 'unocss/astro';
import astroIcon from 'astro-icon';
import { CUSTOM_DOMAIN, BASE_PATH } from './src/server-constants.ts';

// https://astro.build/config
export default defineConfig({
  site: CUSTOM_DOMAIN || 'https://zhangjian0248.top',
  base: BASE_PATH || '/blog',
  integrations: [
    Unocss({
      injectReset: true,
    }),
    astroIcon(),
  ],
});
