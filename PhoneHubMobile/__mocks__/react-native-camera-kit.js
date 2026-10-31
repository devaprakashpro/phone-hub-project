/**
 * Jest manual mock — the real package is a native UI component that pulls in
 * RN codegen specs jest can't parse. The render test only needs a stand-in.
 */
const React = require('react');
const {View} = require('react-native');

const Camera = React.forwardRef((props, ref) => React.createElement(View, {...props, ref}));
Camera.displayName = 'Camera';

module.exports = {Camera, CameraType: {Back: 'back', Front: 'front'}};
