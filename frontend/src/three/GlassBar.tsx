/* eslint-disable react/no-unknown-property */
import { useMemo, type ReactNode } from "react";
import * as THREE from "three";
import { ModeWrapper } from "./ModeWrapper";

interface GlassBarProps {
  children?: ReactNode;
  scale?: number;
  ior?: number;
  thickness?: number;
  chromaticAberration?: number;
  transmission?: number;
  roughness?: number;
  anisotropy?: number;
}

export function GlassBar({
  children,
  scale = 1,
  ior = 1.15,
  thickness = 10,
  chromaticAberration = 0.05,
  transmission = 1,
  roughness = 0,
  anisotropy = 0.1,
}: GlassBarProps) {
  const geometry = useMemo(() => new THREE.BoxGeometry(12, 0.8, 0.8), []);

  return (
    <ModeWrapper
      geometry={geometry}
      lockToBottom
      followPointer={false}
      scale={scale}
      ior={ior}
      thickness={thickness}
      chromaticAberration={chromaticAberration}
      transmission={transmission}
      roughness={roughness}
      anisotropy={anisotropy}
    >
      {children}
    </ModeWrapper>
  );
}
