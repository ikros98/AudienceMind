/* eslint-disable react/no-unknown-property */
import { useMemo, type ReactNode } from "react";
import * as THREE from "three";
import { ModeWrapper } from "./ModeWrapper";

interface GlassLensProps {
  children?: ReactNode;
  scale?: number;
  ior?: number;
  thickness?: number;
  chromaticAberration?: number;
  transmission?: number;
  roughness?: number;
  anisotropy?: number;
}

export function GlassLens({
  children,
  scale = 1,
  ior = 1.15,
  thickness = 5,
  chromaticAberration = 0.1,
  transmission = 1,
  roughness = 0,
  anisotropy = 0.1,
}: GlassLensProps) {
  const geometry = useMemo(
    () => new THREE.CylinderGeometry(1.5, 1.5, 0.3, 64),
    [],
  );

  return (
    <ModeWrapper
      geometry={geometry}
      followPointer
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
