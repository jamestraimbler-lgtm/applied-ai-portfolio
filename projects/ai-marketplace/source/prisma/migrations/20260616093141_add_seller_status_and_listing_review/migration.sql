-- CreateEnum
CREATE TYPE "SellerStatus" AS ENUM ('ONBOARDING', 'ACTIVE', 'SUSPENDED');

-- CreateEnum
CREATE TYPE "ReviewVerdict" AS ENUM ('PENDING', 'APPROVED', 'REJECTED', 'ESCALATED');

-- CreateEnum
CREATE TYPE "ReviewedBy" AS ENUM ('AGENT', 'HUMAN');

-- AlterEnum
ALTER TYPE "ListingStatus" ADD VALUE 'REJECTED';

-- AlterTable
ALTER TABLE "SellerProfile" ADD COLUMN     "intendedPricingModel" "PricingModel",
ADD COLUMN     "status" "SellerStatus" NOT NULL DEFAULT 'ONBOARDING';

-- CreateTable
CREATE TABLE "ListingReview" (
    "id" TEXT NOT NULL,
    "listingId" TEXT NOT NULL,
    "verdict" "ReviewVerdict" NOT NULL DEFAULT 'PENDING',
    "reviewedBy" "ReviewedBy" NOT NULL DEFAULT 'AGENT',
    "reasoning" TEXT,
    "riskFlags" JSONB,
    "riskScore" INTEGER,
    "modelId" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "resolvedAt" TIMESTAMP(3),

    CONSTRAINT "ListingReview_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "ListingReview_listingId_idx" ON "ListingReview"("listingId");

-- CreateIndex
CREATE INDEX "ListingReview_verdict_idx" ON "ListingReview"("verdict");

-- CreateIndex
CREATE INDEX "ListingReview_verdict_createdAt_idx" ON "ListingReview"("verdict", "createdAt");

-- CreateIndex
CREATE INDEX "SellerProfile_status_idx" ON "SellerProfile"("status");

-- AddForeignKey
ALTER TABLE "ListingReview" ADD CONSTRAINT "ListingReview_listingId_fkey" FOREIGN KEY ("listingId") REFERENCES "Listing"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
