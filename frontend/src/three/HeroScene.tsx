/* eslint-disable react/no-unknown-property */
import { FluidGlass } from "./FluidGlass";

/** Floating colored rectangle as background decoration */
function FloatingRect({
  position,
  color,
  width,
  height,
}: {
  position: [number, number, number];
  color: string;
  width: number;
  height: number;
}) {
  return (
    <mesh position={position}>
      <planeGeometry args={[width, height]} />
      <meshBasicMaterial color={color} opacity={0.25} transparent />
    </mesh>
  );
}

function GraphNode({
  position,
  color,
  radius,
}: {
  position: [number, number, number];
  color: string;
  radius: number;
}) {
  return (
    <mesh position={position}>
      <circleGeometry args={[radius, 32]} />
      <meshBasicMaterial color={color} opacity={0.9} transparent />
    </mesh>
  );
}

function GraphLink({
  position,
  rotation = [0, 0, 0],
  length,
  color,
}: {
  position: [number, number, number];
  rotation?: [number, number, number];
  length: number;
  color: string;
}) {
  return (
    <mesh position={position} rotation={rotation}>
      <planeGeometry args={[length, 0.04]} />
      <meshBasicMaterial color={color} opacity={0.4} transparent />
    </mesh>
  );
}

/** Inner 3D content rendered inside the glass scroll scene */
function HeroAmbientGraph() {
  return (
    <group>
      <FloatingRect position={[-3.2, 1.8, -2.7]} color="#4a6fff" width={1.4} height={0.54} />
      <FloatingRect position={[3.3, 1.2, -3.1]} color="#7ee7ff" width={1.7} height={0.62} />
      <FloatingRect position={[-2.4, -1.15, -2.2]} color="#a78bfa" width={1.2} height={0.46} />
      <FloatingRect position={[2.7, -1.5, -2.9]} color="#c7ccff" width={1.8} height={0.52} />
      <FloatingRect position={[0.1, 2.1, -3.4]} color="#7ee7ff" width={2.1} height={0.22} />

      <GraphLink position={[-1.55, 0.72, -2.35]} rotation={[0, 0, -0.26]} length={1.5} color="#96a9ff" />
      <GraphLink position={[-0.18, 0.18, -2.6]} rotation={[0, 0, 0.42]} length={1.8} color="#7ee7ff" />
      <GraphLink position={[1.48, 0.12, -2.4]} rotation={[0, 0, -0.18]} length={1.52} color="#c7ccff" />
      <GraphLink position={[0.75, -1.0, -2.7]} rotation={[0, 0, 0.3]} length={1.26} color="#a78bfa" />
      <GraphLink position={[-1.95, -0.65, -2.9]} rotation={[0, 0, -0.6]} length={1.12} color="#4a6fff" />

      <GraphNode position={[-2.25, 1.02, -2.0]} color="#7ee7ff" radius={0.16} />
      <GraphNode position={[-0.9, 0.45, -2.25]} color="#4a6fff" radius={0.22} />
      <GraphNode position={[0.38, -0.12, -2.55]} color="#c7ccff" radius={0.14} />
      <GraphNode position={[2.15, 0.38, -2.2]} color="#a78bfa" radius={0.2} />
      <GraphNode position={[1.18, -1.22, -2.5]} color="#7ee7ff" radius={0.15} />
      <GraphNode position={[-2.8, -1.02, -2.3]} color="#4a6fff" radius={0.12} />
      <GraphNode position={[2.95, 1.72, -2.8]} color="#c7ccff" radius={0.1} />

      {/* Ambient light for the scene */}
      <ambientLight intensity={0.6} />
      <pointLight position={[5, 5, 5]} intensity={0.4} />
    </group>
  );
}

export function HeroScene() {
  return (
    <FluidGlass
      mode="bar"
      pages={3}
      className="hero-canvas-wrapper"
    >
      <HeroAmbientGraph />
    </FluidGlass>
  );
}
