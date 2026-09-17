import { ModeToggle } from "./components/ModeToggle";

const SiteHeader = () => {
  return (
    <header className="bg-background sticky top-0 z-10 flex h-(--header-height) shrink-0 items-center gap-2 border-b transition-[width,height] ease-linear">
      <div className="flex w-full items-center gap-1 px-4 lg:gap-2 lg:px-6">
        <h1 className="text-base font-bold">Privacy Helper</h1>
        <div className="ml-auto flex items-center gap-2">
          <ModeToggle />
        </div>
      </div>
    </header>
  );
};

export default SiteHeader;
