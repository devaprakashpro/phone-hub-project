module.exports = {
  preset: '@react-native/jest-preset',
  // These ship untranspiled ESM, so they must be transformed (the default
  // preset ignores everything under node_modules).
  transformIgnorePatterns: [
    'node_modules/(?!(?:.pnpm/)?(' +
      '(jest-)?react-native|@react-native(-community)?|' +
      'react-native-safe-area-context' +
      ')/)',
  ],
};
