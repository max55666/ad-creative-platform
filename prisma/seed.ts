import { PrismaClient } from "@prisma/client";

const prisma = new PrismaClient();

async function main() {
  const user = await prisma.user.upsert({
    where: { email: "demo@internal.local" },
    update: {},
    create: {
      name: "Internal Team",
      email: "demo@internal.local"
    }
  });

  const project = await prisma.project.create({
    data: {
      userId: user.id,
      productName: "智能溫控保溫杯",
      productDescription: "可顯示水溫、長效保溫，適合上班族、學生與送禮情境。",
      productUrl: "https://example.com/products/smart-cup",
      targetMarket: "台灣",
      price: "NT$1,280",
      specs: "500ml、不鏽鋼、LED 溫度顯示、保溫 8 小時",
      mainUseCase: "辦公室、通勤、送禮",
      competitors: "一般保溫杯、品牌溫控杯"
    }
  });

  await prisma.productAnalysis.create({
    data: {
      projectId: project.id,
      summary: {
        oneLine: "主打安全飲水、辦公效率與送禮質感的智能保溫杯。",
        category: "生活用品 / 智能杯具",
        positioning: "中價位實用禮品"
      },
      audienceAnalysis: {
        primary: {
          name: "上班族與送禮族群",
          ageRange: "25-44",
          genderSkew: "中性",
          interestTags: ["辦公好物", "生活風格", "送禮"]
        }
      },
      painPoints: {
        functional: ["不知道水溫是否適合入口", "一般杯子保溫不足"],
        emotional: ["想送實用但有質感的禮物"]
      },
      sellingPoints: {
        core: ["LED 溫度顯示", "長效保溫", "送禮體面"],
        avoidClaims: ["醫療或健康療效宣稱"]
      },
      adAngles: [
        { angle: "痛點型", audience: "上班族", message: "不用再猜水溫", risk: "避免誇大科技感" }
      ],
      nextSteps: ["拍攝辦公桌使用場景", "測試送禮型素材"]
    }
  });
}

main()
  .then(async () => {
    await prisma.$disconnect();
  })
  .catch(async (error) => {
    console.error(error);
    await prisma.$disconnect();
    process.exit(1);
  });
