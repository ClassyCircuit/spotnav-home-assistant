import { readFile } from 'node:fs/promises';

// Web Awesome 3.14.0 registers each component (including transitive imports)
// through Lit's legacy customElement decorator. Guard only those decorators in
// our bundles, not the registry or Lit used by Home Assistant/other resources.
export const webAwesomeRegistration = {
  name: 'spotnav-web-awesome-registration',
  setup(build) {
    build.onLoad({ filter: /chunk\.[A-Z0-9]+\.js$/ }, async args => {
      if (!/[\\/]@awesome\.me[\\/]webawesome[\\/]dist[\\/]chunks[\\/]/.test(args.path)) return;
      const source = await readFile(args.path, 'utf8');
      const contents = source.replace(/customElement\("(wa-[a-z0-9-]+)"\)/g,
        (_, name) => `((...args) => { if (!customElements.get("${name}")) return customElement("${name}")(...args); })`);
      return { contents, loader: 'js' };
    });
  },
};
