import React from 'react';
import {Pressable, Text} from 'react-native';
import {styles as s} from '../theme';
export function Button({label, onPress, disabled = false, secondary = false}: {
  label: string; onPress: () => void; disabled?: boolean; secondary?: boolean;
}) {
  return <Pressable accessibilityRole="button" accessibilityState={{disabled}} onPress={onPress} disabled={disabled}
    style={[s.button, secondary && s.secondary, disabled && s.disabled]}>
    <Text style={[s.buttonText, secondary && s.secondaryText]}>{label}</Text>
  </Pressable>;
}
