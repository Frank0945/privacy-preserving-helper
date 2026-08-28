import { Separator } from "@/components/atoms/separator";

const NotFoundPage = () => {
  return (
    <main className="flex h-screen flex-1 flex-row items-center justify-center space-x-5">
      <h1 className="text-3xl font-bold">404</h1>
      <div className="h-12">
        <Separator orientation="vertical" />
      </div>
      <p className="text-lg">Page Not Found</p>
    </main>
  );
};
export default NotFoundPage;
