/* eslint-disable react/no-unknown-property */
import type { ReactNode } from "react";
import { Canvas } from "@react-three/fiber";
import { Preload, ScrollControls, Scroll } from "@react-three/drei";
import { GlassBar } from "./GlassBar";
import { GlassLens } from "./GlassLens";

type Mode = "lens" | "bar";

interface FluidGlassProps {
  mode?: Mode;
  children?: ReactNode;
  pages?: number;
  className?: string;
  thickness?: number;
  ior?: number;
  chromaticAberration?: number;
  transmission?: number;
  roughness?: number;
  anisotropy?: number;
  scale?: number;
}

export function FluidGlass({
  mode = "bar",
  children,
  pages = 1,
  className,
  thickness,
  ior,
  chromaticAberration,
  transmission,
  roughness,
  anisotropy,
  scale,
}: FluidGlassProps) {
  const materialProps = {
    ...(thickness != null && { thickness }),
    ...(ior != null && { ior }),
    ...(chromaticAberration != null && { chromaticAberration }),
    ...(transmission != null && { transmission }),
    ...(roughness != null && { roughness }),
    ...(anisotropy != null && { anisotropy }),
    ...(scale != null && { scale }),
  };

  const GlassComponent = mode === "lens" ? GlassLens : GlassBar;

  return (
    <div className={className}>
      <Canvas
        camera={{ position: [0, 0, 20], fov: 15 }}
        gl={{ alpha: true }}
      >
        <ScrollControls pages={pages} damping={4}>
          <GlassComponent {...materialProps}>
            <Scroll>
              {children}
            </Scroll>
          </GlassComponent>
        </ScrollControls>
        <Preload all />
      </Canvas>
    </div>
  );
}
