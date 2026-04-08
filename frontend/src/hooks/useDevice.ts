import { useEffect, useState } from "react";

type Device = "mobile" | "tablet" | "desktop";

const BREAKPOINTS = { mobile: 639, tablet: 1023 } as const;

function getDevice(): Device {
  const w = window.innerWidth;
  if (w <= BREAKPOINTS.mobile) return "mobile";
  if (w <= BREAKPOINTS.tablet) return "tablet";
  return "desktop";
}

export function useDevice(): Device {
  const [device, setDevice] = useState<Device>(getDevice);

  useEffect(() => {
    const onResize = () => setDevice(getDevice());
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  return device;
}
