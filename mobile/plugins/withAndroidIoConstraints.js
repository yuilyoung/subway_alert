const { withAppBuildGradle } = require('expo/config-plugins');
const { mergeContents } = require('@expo/config-plugins/build/utils/generateCode');

// Expo Constants, FileSystem and React Native request these transitive dependencies.
// Constraints let newer compatible versions from future SDKs take precedence.
module.exports = function withAndroidIoConstraints(config) {
  return withAppBuildGradle(config, (mod) => {
    mod.modResults.contents = mergeContents({
      src: mod.modResults.contents,
      tag: 'android-io-constraints',
      anchor: /^dependencies\s*\{/,
      offset: 1,
      comment: '//',
      newSrc: [
        '    constraints {',
        '        implementation("commons-io:commons-io:2.14.0")',
        '        implementation("com.squareup.okio:okio:3.4.0")',
        '    }',
      ].join('\n'),
    }).contents;
    return mod;
  });
};
