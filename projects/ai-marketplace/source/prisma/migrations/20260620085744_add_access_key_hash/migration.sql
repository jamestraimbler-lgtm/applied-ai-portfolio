-- AlterTable
ALTER TABLE "Subscription" ADD COLUMN     "accessKeyHash" TEXT;

-- CreateIndex
CREATE INDEX "Subscription_accessKeyHash_idx" ON "Subscription"("accessKeyHash");
